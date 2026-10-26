"""
Tests for issue #195: Twitch Extension Resubmission (1.3.0)
(markdown/plans/plan-issue-195-twitch-extension-resubmission.md).

Story 1 — Submission Guide Matches the 1.3.0 Build
Story 2 — Listing Copy Says Only What the Extension Does
Story 3 — Reviewer Disclosure Matches the Packaged Code
Story 4 — Testing Instructions Follow the Current Panel
Story 5 — Reviewer Sees What Changed Since the Rejection

These are static repo checks (the submission guide's contents, the packaged
twitch-extension/ files, backend routes, package.sh output) rather than
application logic. package.sh is run via subprocess against a copy of
twitch-extension/ in pytest's tmp_path, so no zip is written into the repo.
Backend routes come from `main.app.routes`, imported with DEBUG=true as other
tests do. All paths resolve from the repo root so the suite runs from backend/.

Manual verification (not automated):
- Production deploy of the current `main`, with migration 038 run after
  `scripts/backup-db.sh`.
- Production env vars actually set: TWITCH_EXTENSION_CLIENT_ID,
  TWITCH_EXTENSION_SECRET, TWITCH_EXTENSION_VERSION=1.3.0.
- Admin › Twitch › Twitch status shows every check green on production before
  Submit.
- Console fields completed (Asset Hosting, Panel Height 500, URL Fetching and
  Image Domains allowlists, Chat + Request Identity Link capabilities,
  Configuration Service); review channel approved as a streamer.
- Rehearsal on test: Flows 1-5 walked word for word in Hosted Test with dev
  tools open (no 404, no CSP violation, Connection check ok).
- Screenshots retaken for 1.3.0 (Live tab not joined, Cards with a reveal,
  Roster, Settings with Leave, broadcaster MVP selection); icon sizes meet the
  console's current spec.
- Upload of 1.3.0 and Submit with the pasted listing / reviewer blocks.
"""
import html
import pathlib
import re
import shutil
import subprocess

import pytest

# backend/tests/ -> backend/ -> repo root
REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
EXT_DIR = REPO_ROOT / "twitch-extension"
PACKAGE_SH = EXT_DIR / "package.sh"
SUBMISSION_DOC = (
    REPO_ROOT / "markdown" / "features" / "reference" / "twitch-extension-review-submission.md"
)
RESUBMISSION_FEATURE_DOC = (
    REPO_ROOT / "markdown" / "features" / "reference" / "twitch-extension-resubmission.md"
)
PACKAGED_JS = ["panel.js", "extension.js", "live_config.js", "config.js"]


def _require_zip():
    if shutil.which("zip") is None:
        pytest.skip("zip is not installed")


def _ext_copy(tmp_path):
    dest = tmp_path / "twitch-extension"
    shutil.copytree(EXT_DIR, dest, ignore=shutil.ignore_patterns("*.zip"))
    return dest


_ORIGIN = ("--ebs-origin", "https://kana-cards.com")


def _run_package(ext_dir, *args):
    return subprocess.run(
        ["bash", str(ext_dir / "package.sh"), *args],
        capture_output=True, text=True, timeout=60,
    )


def _submission_doc():
    return SUBMISSION_DOC.read_text()


def _section(text, start, end):
    """Text from `start` up to (not including) the next `end`."""
    i = text.index(start)
    j = text.index(end, i + len(start))
    return text[i:j]


def _flat(text):
    """Markdown block as one line: quote markers and bold removed, whitespace collapsed."""
    lines = [re.sub(r"^\s*>\s?", "", line) for line in text.splitlines()]
    return " ".join(" ".join(lines).replace("**", "").split())


def _header():
    return _submission_doc().split("## Submission checklist")[0]


def _checklist():
    return _section(_submission_doc(), "## Submission checklist", "## Listing copy")


def _checklist_items(text):
    """Each `- [ ]` item of a checklist, flattened."""
    parts = re.split(r"^- \[ \] ", text, flags=re.M)[1:]
    return [_flat(p.split("\n\n")[0]) for p in parts]


# Required checklist order (plan Story 1): one marker per item; the callable
# matches the bare "Submit" item.
CHECKLIST_ORDER = [
    ("production deploy", "migration 038"),
    ("env vars", "TWITCH_EXTENSION_VERSION=1.3.0"),
    ("drop age for the review window", "TWITCH_DROP_MIN_ACCOUNT_AGE_HOURS=0"),
    ("Extension Settings", "Developer Writable Channel Segment Version"),
    ("global ebs_url", "set-ebs-url.sh"),
    ("Asset Hosting + Panel Height", "Panel Height"),
    ("URL Fetching allowlist", "Allowlist for URL Fetching Domains"),
    ("Image Domains allowlist", "Allowlist for Image Domains"),
    ("Chat + Request Identity Link", "Request Identity Link"),
    ("approve review channel", "Approved streamers"),
    ("Connection check", "Connection check"),
    ("Hosted Test", "Hosted Test"),
    ("Submit", lambda item: item.strip() == "Submit"),
]


def _checklist_order_problems(items):
    """Required items that are missing or out of order (empty when fine)."""
    problems, last = [], -1
    for name, marker in CHECKLIST_ORDER:
        match = marker if callable(marker) else (lambda item, m=marker: m.lower() in item.lower())
        idx = next((i for i, item in enumerate(items) if match(item)), None)
        if idx is None:
            problems.append(f"missing: {name}")
            continue
        if idx < last:
            problems.append(f"out of order: {name}")
        last = max(last, idx)
    return problems


def _description_block():
    return _section(_submission_doc(), "**Description** (full):", "This wording is deliberately")


def _mentions_weekly_grant(text):
    return "weekly grant" in _flat(text).lower()


def _ebs_section():
    return _section(_submission_doc(), "## EBS URL disclosure", "### Endpoints the Extension frontend calls")


def _ebs_paste_block():
    return "\n".join(l for l in _ebs_section().splitlines() if l.startswith(">"))


# A `"/twitch/.../" + expr` call site becomes the backend route's path parameter.
PARAM_BY_PREFIX = {
    "/twitch/draw/booster/": "team_id",
    "/twitch/roster/activate/": "card_id",
    "/twitch/roster/deactivate/": "card_id",
}


def _called_paths(js_text):
    """`/twitch/...` string literals in JS. A literal ending in `/` and followed by
    `+ <expression>` is normalised to its `{param}` form."""
    paths = set()
    for m in re.finditer(r"[\"'](/twitch/[a-z_/]+)[\"']\s*(\+)?", js_text):
        path, plus = m.group(1), m.group(2)
        if path.endswith("/") and plus:
            path += "{" + PARAM_BY_PREFIX.get(path, "param") + "}"
        paths.add(path)
    return paths


def _packaged_called_paths():
    paths = set()
    for name in PACKAGED_JS:
        paths |= _called_paths((EXT_DIR / name).read_text())
    return paths


def _endpoint_rows():
    """(paths, method) for each row of the guide's endpoint table."""
    doc = _submission_doc()
    start = doc.index("### Endpoints the Extension frontend calls")
    end = doc.index("\n## ", start)
    rows = []
    for line in doc[start:end].splitlines():
        if not line.startswith("|") or line.startswith("|---") or line.startswith("| Path"):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        rows.append((re.findall(r"`(/twitch/[^`]+)`", cells[0]), cells[1]))
    return rows


def _table_paths(rows):
    return {p for paths, _ in rows for p in paths}


def _coverage_problems(called, table):
    """(called but not in the table, in the table but never called)."""
    return sorted(called - table), sorted(table - called)


def _api_routes(routes, prefix=""):
    """Every APIRoute with its full path, walking included routers
    (lessons-learned 2026-10-08; the same walk as test_issue_184)."""
    from fastapi.routing import APIRoute
    for route in routes:
        if isinstance(route, APIRoute):
            yield prefix + route.path, route
        elif getattr(route, "original_router", None) is not None:
            context = getattr(route, "include_context", None)
            extra = getattr(context, "prefix", "") or ""
            yield from _api_routes(route.original_router.routes, prefix + extra)
        elif getattr(route, "routes", None) is not None and not hasattr(route, "app"):
            yield from _api_routes(route.routes, prefix)


def _backend_twitch_routes():
    """{path: methods} of the backend's /twitch routes, without the catch-all 404 route."""
    import main
    out = {}
    for path, route in _api_routes(main.app.routes):
        if path.startswith("/twitch/") and "{rest:path}" not in path:
            out.setdefault(path, set()).update(route.methods or ())
    return out


def _route_problems(rows, routes):
    """Table paths with no backend route, or whose route doesn't accept the row's method."""
    problems = []
    for paths, method in rows:
        for path in paths:
            if path not in routes:
                problems.append(f"no route: {path}")
            elif method not in routes[path]:
                problems.append(f"{path} does not accept {method}")
    return problems


def _steps_section():
    doc = _submission_doc()
    start = doc.index("\n", doc.index("## Steps to reproduce"))
    return doc[start:doc.index("## Security fix made for this submission")]


def _quoted(text):
    """Double-quoted strings outside backtick spans, whitespace collapsed."""
    text = re.sub(r"`[^`]*`", "", text)
    return [" ".join(q.split()) for q in re.findall(r'"([^"]+)"', text)]


FLOW_SOURCES = ["panel.html", "panel.js", "extension.js", "config.html", "config.js",
                "live_config.html", "live_config.js"]


def _flow_source_text():
    return " ".join(" ".join(html.unescape((EXT_DIR / n).read_text()).split()) for n in FLOW_SOURCES)


def _stale_quotes(quotes, source):
    """Quotes whose literal parts (split at `<...>` placeholders) are not all in the source."""
    stale = []
    for q in quotes:
        parts = [p.strip() for p in re.split(r"<[^>]+>", q) if p.strip()]
        if not parts or any(p not in source for p in parts):
            stale.append(q)
    return stale


def _changes_block():
    section = _section(_submission_doc(), "### Changes since the last review", "## Steps to reproduce")
    return "\n".join(l for l in section.splitlines() if l.startswith(">"))


def _issue_refs(text):
    return re.findall(r"#\d+", text)


def _change_log():
    doc = _submission_doc()
    start = doc.index("### 2026-10 — Version 1.3.0 change log")
    nxt = doc.find("\n### ", start + 1)
    return doc[start:] if nxt == -1 else doc[start:nxt]


def _package_files_list():
    src = PACKAGE_SH.read_text()
    block = re.search(r"^FILES=\((.*?)^\)", src, re.S | re.M).group(1)
    return [line.strip() for line in block.splitlines() if line.strip()]


# ---------------------------------------------------------------------------
# Story 1 — Submission Guide Matches the 1.3.0 Build
# ---------------------------------------------------------------------------

class TestSubmissionGuideMatchesBuild:
    """As the operator submitting the extension, I want the submission guide to
    describe exactly the build I upload so that I can fill in Twitch's form
    without guessing and nothing I paste contradicts the extension."""

    def test_guide_header_and_checklist_name_version_1_3_0(self):
        """The guide's header and checklist name version 1.3.0 and the build command `bash twitch-extension/package.sh 1.3.0 --ebs-origin https://kana-cards.com`."""
        header, checklist = _header(), _checklist()
        command = "bash twitch-extension/package.sh 1.3.0 --ebs-origin https://kana-cards.com"
        assert "twitch-extension-1.3.0.zip" in header
        assert command in _flat(header)
        assert "twitch-extension-1.3.0.zip" in checklist
        assert command in _flat(checklist)

    def test_guide_says_1_2_x_was_test_only(self):
        """The guide says 1.2.0 and 1.2.1 were test-only and are not submitted."""
        flat = _flat(_header()).replace("`", "")
        assert "1.2.0 and 1.2.1 were used in the console for testing only and are not submitted" in flat

    def test_guide_does_not_name_1_2_0_zip_for_upload(self):
        """Failure path: the header/checklist no longer name twitch-extension-1.2.0.zip (or 1.2.x) as the version to upload."""
        head = _header() + _checklist()
        assert not re.search(r"twitch-extension-1\.2\.\d+\.zip", head)
        assert not re.search(r"package\.sh 1\.2\.", head)
        assert not re.search(r"\b1\.2\.\d", _checklist())

    def test_checklist_contains_required_console_items(self):
        """The checklist contains "Panel Height", "500", "Allowlist for URL Fetching Domains", "Allowlist for Image Domains", "Request Identity Link", "Chat", "Configuration Service", "Connection check" and "Twitch status"."""
        flat = _flat(_checklist())
        for needle in ("Panel Height", "500", "Allowlist for URL Fetching Domains",
                       "Allowlist for Image Domains", "Request Identity Link", "Chat",
                       "Configuration Service", "Connection check", "Twitch status"):
            assert needle in flat, needle

    def test_checklist_items_in_required_order(self):
        """Checklist order: production deploy (migration 038 after scripts/backup-db.sh) → env vars → Asset Hosting + Panel Height 500 → URL Fetching allowlist → Image Domains allowlist → Chat + Request Identity Link with Configuration Service → approve review channel → Connection check → Hosted Test → Submit."""
        items = _checklist_items(_checklist())
        assert _checklist_order_problems(items) == []
        panel_height = next(i for i in items if "Panel Height" in i)
        assert "Asset Hosting" in panel_height and "500" in panel_height
        caps = next(i for i in items if "Request Identity Link" in i)
        assert "Chat" in caps and "Configuration Service" in caps
        settings = next(i for i in items if i.startswith("Extension Settings"))
        assert "Configure method: Extension Configuration Service" in settings
        assert "Developer Writable Channel Segment Version left empty" in settings
        ebs = next(i for i in items if "set-ebs-url.sh" in i)
        assert "ebs_url" in ebs
        ebs_urls = re.findall(r"https?://[^\s`]+", ebs)
        assert ebs_urls and all(u == "https://kana-cards.com" for u in ebs_urls), ebs_urls
        drop_age = next(i for i in items if "TWITCH_DROP_MIN_ACCOUNT_AGE_HOURS=0" in i)
        after = next(i for i in items if i.startswith("After the review"))
        assert items.index(drop_age) < items.index("Submit") < items.index(after)
        assert "TWITCH_DROP_MIN_ACCOUNT_AGE_HOURS" in after

    def test_checklist_migration_038_after_backup_script(self):
        """The production deploy item mentions migration 038 after scripts/backup-db.sh (backup is named before the migration)."""
        deploy = next(i for i in _checklist_items(_checklist()) if "migration 038" in i.lower())
        assert "scripts/backup-db.sh" in deploy and "main" in deploy
        # The log line appears once; an already-migrated database is checked in schema_migrations.
        assert "schema_migrations" in deploy
        import migrate
        assert "038_twitch_starter_grants_backfill" in [m[0] for m in migrate.MIGRATIONS]
        assert "INSERT INTO schema_migrations" in pathlib.Path(migrate.__file__).read_text()
        assert deploy.index("scripts/backup-db.sh") < deploy.lower().index("migration 038")

    def test_checklist_names_production_env_vars(self):
        """The checklist names TWITCH_EXTENSION_CLIENT_ID, TWITCH_EXTENSION_SECRET and TWITCH_EXTENSION_VERSION=1.3.0."""
        flat = _flat(_checklist())
        for var in ("TWITCH_EXTENSION_CLIENT_ID", "TWITCH_EXTENSION_SECRET", "TWITCH_EXTENSION_VERSION=1.3.0"):
            assert var in flat, var

    def test_checklist_image_domains_names_default_logo_hosts(self):
        """The Image Domains item names the https:// Steam CDN hosts from backend/logo_hosts.py DEFAULT_LOGO_HOSTS, or points to Admin › Twitch › Twitch status."""
        from logo_hosts import DEFAULT_LOGO_HOSTS
        item = next(i for i in _checklist_items(_checklist()) if "Allowlist for Image Domains" in i)
        for host in DEFAULT_LOGO_HOSTS:
            assert f"https://{host}" in item, host
        assert "Admin › Twitch › Twitch status" in item

    def test_guide_notes_capabilities_editable_only_in_local_test(self):
        """The guide notes that capability fields can be edited only in Local Test."""
        flat = _flat(_submission_doc())
        assert "editable only while the version is in Local Test" in flat
        note = flat[flat.index("Capability fields"):flat.index("editable only while")]
        for field in ("URL Fetching Domains", "Image Domains", "Chat", "Request Identity Link"):
            assert field in note, field

    def test_guide_has_twitch_status_go_no_go_line(self):
        """The guide has a go/no-go line: Admin › Twitch › Twitch status shows every check green on production before Submit."""
        items = _checklist_items(_checklist())
        go = next(i for i in items if "Go/no-go" in i)
        assert "Admin › Twitch › Twitch status" in go
        assert "every check green" in go and "production" in go
        # Warnings for settings the extension doesn't need are explained (twitch_status.py).
        assert "Connect Twitch" in go and "STEAM_API_KEY" in go
        assert "No check may show a problem" in go
        status = (pathlib.Path(__file__).resolve().parent.parent / "twitch_status.py").read_text()
        assert '"connect_twitch", WARNING' in status and '"steam_api_key", WARNING' in status
        assert items.index(go) < items.index("Submit")

    def test_checklist_order_check_detects_misordered_items(self):
        """Failure path: the checklist-order helper rejects a checklist where Submit precedes Hosted Test (or an item is missing)."""
        good = _checklist_items(_checklist())
        assert _checklist_order_problems(good) == []
        hosted = next(i for i in good if i.startswith("Hosted Test"))
        swapped = [i for i in good if i not in (hosted, "Submit")] + ["Submit", hosted]
        assert _checklist_order_problems(swapped) == ["out of order: Submit"]
        missing = [i for i in good if "Allowlist for Image Domains" not in i]
        assert "missing: Image Domains allowlist" in _checklist_order_problems(missing)

    def test_package_sh_prints_image_domains_reminder_after_panel_height(self, tmp_path):
        """On success, package.sh prints "Allowlist for Image Domains: see Admin › Twitch › Twitch status" after the Panel Height line (run in a tmp copy)."""
        _require_zip()
        ext = _ext_copy(tmp_path)
        result = _run_package(ext, "1.3.0", *_ORIGIN)
        assert result.returncode == 0, result.stdout + result.stderr
        reminder = "Allowlist for Image Domains: see Admin › Twitch › Twitch status"
        lines = result.stdout.splitlines()
        height = next(i for i, l in enumerate(lines) if "Panel Height: 500" in l)
        image = next(i for i, l in enumerate(lines) if reminder in l)
        # Right after the Panel Height reminder; only its one-line explanation sits between.
        assert height < image <= height + 2
        assert (ext / "twitch-extension-1.3.0.zip").is_file()
        # One Image Domains note, not two.
        assert result.stdout.count("Allowlist for Image Domains") == 1
        assert result.stdout.count("monogram") == 1

    def test_package_sh_failed_build_prints_no_image_domains_reminder(self, tmp_path):
        """Failure path: when package.sh exits non-zero (no --ebs-origin / no version), the Image Domains reminder is not printed and no zip is created."""
        ext = _ext_copy(tmp_path)
        for args in (("1.3.0",), ()):
            result = _run_package(ext, *args)
            assert result.returncode != 0
            assert "Allowlist for Image Domains" not in result.stdout + result.stderr
        assert not list(ext.glob("twitch-extension-*.zip"))


# ---------------------------------------------------------------------------
# Story 2 — Listing Copy Says Only What the Extension Does
# ---------------------------------------------------------------------------

class TestListingCopyAccurate:
    """As a Twitch reviewer, I want the listing to describe the extension
    accurately so that what I read matches what I test."""

    def test_listing_has_no_weekly_grant(self):
        """The description no longer mentions a weekly grant (a test fails if the listing mentions "weekly grant")."""
        assert not _mentions_weekly_grant(_description_block())

    def test_listing_mentions_starter_tokens_and_mvp_drops(self):
        """The description says joining gives starter tokens, and more come from MVP drops when the broadcaster confirms a match MVP."""
        flat = _flat(_description_block())
        assert "Joining gives starter tokens" in flat
        assert "MVP drop" in flat
        assert "when the broadcaster picks a match MVP" in flat
        # Who gets a drop, as twitch.py picks them: panel open, at most TWITCH_DROP_MAX, not too new.
        assert "up to 20 joined viewers who have the panel open, picked at random" in flat
        assert "new players are included after a waiting period" in flat
        assert "currently watching" not in flat and "viewers watching" not in flat
        live_config = " ".join((EXT_DIR / "live_config.html").read_text().split())
        assert "joined viewers who have the panel open" in live_config
        assert 'os.getenv("TWITCH_DROP_MAX", "20")' in (
            pathlib.Path(__file__).resolve().parent.parent / "twitch.py").read_text()

    def test_listing_keeps_chat_no_purchase_and_leave_statements(self):
        """The description still has the **Twitch Chat** paragraph, the no-purchase statement and the Leave statement."""
        block = _description_block()
        flat = _flat(block)
        assert "**Twitch Chat:**" in block
        assert "no purchase or payment involved" in flat
        assert "Players can leave at any time in the panel's Settings, which deletes their game data." in flat

    def test_listing_token_wording_matches_join_view_and_config_html(self):
        """The token wording matches the panel's join view ("win tokens when the broadcaster picks a match MVP") and config.html."""
        flat = _flat(_description_block())
        panel = (EXT_DIR / "panel.html").read_text()
        join = re.search(r'<template id="tpl-join">(.*?)</template>', panel, re.S).group(1)
        assert "win tokens when the broadcaster picks a match MVP" in join
        assert "win more tokens when the broadcaster picks a match MVP" in flat
        config = " ".join((EXT_DIR / "config.html").read_text().split())
        assert "win tokens from MVP drops" in config
        assert "MVP drop" in flat

    def test_weekly_grant_check_flags_injected_text(self):
        """Failure path: the listing check reports a description block that contains "weekly grant"."""
        block = _description_block()
        injected = block.replace("Joining gives starter tokens",
                                 "Tokens come from a weekly\n> grant. Joining gives starter tokens")
        assert injected != block
        assert _mentions_weekly_grant(injected)
        assert not _mentions_weekly_grant(block)


# ---------------------------------------------------------------------------
# Story 3 — Reviewer Disclosure Matches the Packaged Code
# ---------------------------------------------------------------------------

class TestReviewerDisclosureMatchesCode:
    """As a Twitch reviewer, I want every backend address and path the
    extension contacts disclosed so that I can verify the extension against
    its submission notes."""

    def test_ebs_block_describes_baked_origins(self):
        """The EBS block says allowed origins are fixed in the package at build time (ebs-origins.js, written by package.sh), ebs_url is used only when its origin is allowed, and the submitted package allows only https://kana-cards.com."""
        section = _flat(_ebs_section()).replace("`", "")
        block = _flat(_ebs_paste_block()).replace("`", "")
        assert "fixed in this package at build time" in block
        assert "ebs-origins.js" in block and "EBS_ALLOWED_ORIGINS" in block
        assert "package.sh" in section
        assert "uses it only when its origin is one of the packaged origins" in block
        assert "This package allows only https://kana-cards.com." in block
        # The code the disclosure describes.
        assert "var EBS_ALLOWED_ORIGINS = " in PACKAGE_SH.read_text()
        assert "_ebsUrlAllowed" in (EXT_DIR / "extension.js").read_text()

    def test_ebs_block_does_not_say_not_hardcoded(self):
        """Failure path: the EBS block no longer claims the backend URL is "not hardcoded"."""
        section = _flat(_ebs_section()).lower()
        assert "not hardcoded" not in section
        assert "does not hardcode" not in section

    def test_endpoint_table_lists_every_packaged_twitch_path(self):
        """Every /twitch/... path called from panel.js, extension.js, live_config.js and config.js appears in the guide's endpoint table."""
        missing, _ = _coverage_problems(_packaged_called_paths(), _table_paths(_endpoint_rows()))
        assert missing == []

    def test_endpoint_table_has_no_path_not_called_by_package(self):
        """Every path in the guide's endpoint table is called by at least one packaged JS file."""
        _, extra = _coverage_problems(_packaged_called_paths(), _table_paths(_endpoint_rows()))
        assert extra == []

    def test_endpoint_table_includes_check_and_ping(self):
        """The endpoint table includes /twitch/check and /twitch/ping, called from config.js (Connection check)."""
        assert {"/twitch/check", "/twitch/ping"} <= _table_paths(_endpoint_rows())
        assert {"/twitch/check", "/twitch/ping"} <= _called_paths((EXT_DIR / "config.js").read_text())
        rows = [l for l in _submission_doc().splitlines()
                if l.startswith("| `/twitch/check`") or l.startswith("| `/twitch/ping`")]
        assert len(rows) == 2
        for line in rows:
            assert "`config.js`" in line and "Connection check" in line

    def test_endpoint_path_extraction_normalises_params(self):
        """Path extraction maps a trailing `/` followed by a variable to the {param} form ({card_id}, {team_id})."""
        js = ('ebsPost("/twitch/draw/booster/" + encodeURIComponent(t.team_id));\n'
              'ebsPost("/twitch/roster/activate/" + encodeURIComponent(benchId) + "?slot=" + slot);\n'
              'ebsPost("/twitch/roster/deactivate/" + encodeURIComponent(current.id));\n'
              'ebsGet("/twitch/me");\n'
              '// a comment mentioning /twitch/status is not a call\n')
        assert _called_paths(js) == {
            "/twitch/draw/booster/{team_id}", "/twitch/roster/activate/{card_id}",
            "/twitch/roster/deactivate/{card_id}", "/twitch/me",
        }
        assert _called_paths('ebsPost("/twitch/new/" + x)') == {"/twitch/new/{param}"}
        assert "/twitch/draw/booster/{team_id}" in _packaged_called_paths()

    def test_endpoint_coverage_detects_missing_table_row(self):
        """Failure path: removing a row from the extracted table (or adding an uncalled path) makes the coverage comparison report that path."""
        called = _packaged_called_paths()
        table = _table_paths(_endpoint_rows())
        assert _coverage_problems(called, table - {"/twitch/ping"}) == (["/twitch/ping"], [])
        assert _coverage_problems(called, table | {"/twitch/status"}) == ([], ["/twitch/status"])

    def test_endpoint_table_paths_have_backend_routes(self):
        """Every table path matches a route in main.app.routes (backend/twitch.py or the routers)."""
        rows = _endpoint_rows()
        assert rows
        assert _route_problems(rows, _backend_twitch_routes()) == []

    def test_backend_route_check_flags_unknown_path(self):
        """Failure path: the route check reports a table path with no matching backend route (e.g. /twitch/does_not_exist)."""
        routes = _backend_twitch_routes()
        assert "/twitch/{rest:path}" not in routes
        assert _route_problems([(["/twitch/does_not_exist"], "GET")], routes) == ["no route: /twitch/does_not_exist"]
        assert _route_problems([(["/twitch/ping"], "POST")], routes) == ["/twitch/ping does not accept POST"]

    def test_disclosure_names_default_logo_hosts_https_only(self):
        """The disclosure names each host in logo_hosts.DEFAULT_LOGO_HOSTS and says logos are shown only from https:// URLs."""
        from logo_hosts import DEFAULT_LOGO_HOSTS
        block = _flat(_ebs_paste_block())
        for host in DEFAULT_LOGO_HOSTS:
            assert host in block, host
        assert "only from `https://` URLs" in block
        # The panel itself enforces it.
        assert r"/^https:\/\//.test(t.logo_url)" in (EXT_DIR / "panel.js").read_text()


# ---------------------------------------------------------------------------
# Story 4 — Testing Instructions Follow the Current Panel
# ---------------------------------------------------------------------------

class TestTestingInstructionsCurrent:
    """As a Twitch reviewer, I want step-by-step testing instructions that
    match the current panel so that I can exercise every feature in one
    session."""

    def test_flows_cover_all_panel_features(self):
        """Flows cover: logged out (Live tab); Join (identity share may be declined), starter tokens, draw, team draw, roster change; broadcaster MVP selection, chat message and token drop; Leave; configuration page Connection check showing "ok"."""
        flat = _flat(_steps_section())
        for needle in (
            "Flow 1", "logged out", "Live tab",
            "Flow 2", "Join Kana Cards", "either answer works", "tokens", "Draw · 1",
            "Team draw · 3", "+ Add a card", "Change",
            "Flow 3", "Select match MVP", "Confirm MVP & Drop Tokens", "Match MVP:",
            "+1 token from the MVP drop",
            "Flow 4", "Leave Kana Cards",
            "Flow 5", "configuration page", "Connection check", '"OK"',
        ):
            assert needle in flat, needle

    def test_flow_expected_results_use_current_panel_wording(self):
        """Each flow's expected result quotes text present in panel.html / panel.js (or config.html / config.js for Flow 5)."""
        quotes = _quoted(_steps_section())
        assert len(quotes) >= 10
        assert _stale_quotes(quotes, _flow_source_text()) == []

    def test_flow_wording_check_detects_stale_copy(self):
        """Failure path: a quoted expected result absent from the packaged files (e.g. old link-code copy) is reported by the wording check."""
        source = _flow_source_text()
        stale = "Log into kana-cards.com → Profile → Generate Twitch Code"
        assert _stale_quotes([stale, "You joined Kana Cards with <N> tokens."], source) == [stale]
        assert _quoted('a "b" `c "d"` "e\n f"') == ["b", "e f"]

    def test_testing_note_explains_scroll_and_error_codes(self):
        """A note explains the panel scrolls within its height and that an error shows a short code (E-…) the operator can look up."""
        steps = _steps_section()
        intro = _flat(steps[:steps.index("**Flow 1")])
        assert "scrolls within that height" in intro
        assert "short code" in intro and "E-REACH" in intro
        assert "include the code" in intro  # plus the support contact (plan-issue-195, R3)
        assert "reason codes table" not in intro
        assert '"E-REACH"' in (EXT_DIR / "extension.js").read_text()

    def test_reviewer_test_setup_names_requirements(self):
        """"Reviewer test setup" names the live channel and an active match week, the approved review channel, and TWITCH_EXTENSION_VERSION with Chat enabled for 1.3.0."""
        setup = _flat(_section(_submission_doc(), "## Reviewer test setup", "### Changes since the last review"))
        assert "review channel is actually live" in setup
        assert "active match week" in setup
        assert "Approved streamers" in setup
        assert "`TWITCH_EXTENSION_VERSION=1.3.0`" in setup
        assert "Chat enabled for version 1.3.0" in setup


# ---------------------------------------------------------------------------
# Story 5 — Reviewer Sees What Changed Since the Rejection
# ---------------------------------------------------------------------------

class TestChangesSinceRejection:
    """As a Twitch reviewer re-reviewing the extension, I want a short note on
    what changed since the 1.1.7 rejection so that I can confirm the policy 4.5
    finding is resolved."""

    def test_changes_since_last_review_block_states_required_points(self):
        """A paste-ready "Changes since the last review" block says the extension no longer requires or mentions any external login, everything is played in the panel with the Twitch login, and the identity share is optional."""
        block = _flat(_changes_block())
        assert block
        assert "no longer requires or mentions any external login" in block
        assert "played in the panel with the Twitch login" in block
        assert "identity share is optional" in block

    def test_changes_block_has_no_issue_numbers(self):
        """Failure path: the "Changes since the last review" block contains no `#<digits>` internal issue references."""
        block = _changes_block()
        assert _issue_refs(block) == []
        assert _issue_refs("fixed in #157 and #164") == ["#157", "#164"]
        # Policy 4.5 in spirit: the paste block names no website at all.
        assert "kana-cards" not in block.lower() and "website" not in block.lower()

    def test_review_history_has_1_3_0_change_log(self):
        """Review history has a "2026-10 — Version 1.3.0 change log" table with file and change columns."""
        doc = _submission_doc()
        history = doc[doc.index("## Review history"):]
        assert "### 2026-10 — Version 1.3.0 change log" in history
        assert "| File | Change |" in _change_log()

    def test_change_log_rows_name_packaged_files(self):
        """Each 1.3.0 change log row names a file in package.sh's FILES list (one row per packaged file changed since 1.1.7)."""
        files = _package_files_list()
        assert "panel.js" in files and "ebs-origins.js" in files
        named = []
        for line in _change_log().splitlines():
            if not line.startswith("| `"):
                continue
            names = re.findall(r"`([^`]+)`", line.strip("|").split("|")[0])
            assert len(names) == 1, line
            named.append(names[0])
        assert named
        assert [n for n in named if n not in files] == []
        assert len(named) == len(set(named))

    def test_screenshot_guidance_names_views_to_retake(self):
        """Screenshot guidance names the views to retake for 1.3.0: Live tab not joined, Cards with a reveal, Roster, Settings with Leave, broadcaster MVP selection."""
        section = _flat(_section(_submission_doc(), "## Icon & screenshots", "## Legal"))
        assert "1.3.0" in section
        assert "initials" not in _submission_doc()
        for view in ("Live tab, not joined", "Cards tab with a reveal", "Roster",
                     "Settings with Leave", "MVP selection"):
            assert view in section, view

    def test_review_history_links_resubmission_feature_doc(self):
        """Review history links twitch-extension-resubmission.md ("Details: …"), and that file exists."""
        doc = _submission_doc()
        history = doc[doc.index("## Review history"):]
        assert "Details: [Twitch Extension Resubmission](twitch-extension-resubmission.md)" in history
        assert RESUBMISSION_FEATURE_DOC.is_file()
        feature = RESUBMISSION_FEATURE_DOC.read_text()
        assert "*(planned)*" not in feature
        assert "stub created at feature planning time" not in feature


SUPPORT_EMAIL = "support@kana-cards.com"


def test_walkthrough_has_fixed_support_contact():
    """The pasted Testing Instructions (the submission doc's steps and the plan's walkthrough block)
    name the fixed support email and contain no placeholder, so nothing has to be filled in by hand."""
    steps = _steps_section()
    plan = (REPO_ROOT / "markdown" / "plans" / "plan-issue-195-twitch-extension-resubmission.md").read_text()
    block = plan.split("```text\n", 1)[1].split("\n```", 1)[0]
    for text in (steps, block, _submission_doc()):
        assert "<SUPPORT CONTACT>" not in text and "SUPPORT CONTACT" not in text
    assert steps.count(SUPPORT_EMAIL) >= 2 and block.count(SUPPORT_EMAIL) >= 2
    support = _section(_submission_doc(), "## Support contact", "## EBS URL disclosure")
    assert SUPPORT_EMAIL in support
