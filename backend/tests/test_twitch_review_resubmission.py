"""
Tests for the Twitch Extension Review Resubmission plan
(markdown/plans/plan-twitch-review-resubmission.md).

Story 1 — Reviewer Can Load Every Extension View (version bump only)
Story 3 — Package Self-Check Before Upload
Story 4 — Chat Usage Disclosed in Listing

These are static repo checks (file contents, package.sh behaviour) rather than
application logic. package.sh is exercised via subprocess against a copy of
twitch-extension/ in pytest's tmp_path, so no real zip is ever written into
the repo. All paths resolve from the repo root so the suite runs from backend/.

Manual verification (not automated) — Twitch dev-console / live-channel steps:
- Story 1: Asset Hosting paths are exactly panel.html / config.html /
  live_config.html (no leading slash or folder prefix).
- Story 1: the submitted version is uploaded and moved to Hosted Test, and all
  three views load without a 404 on a real channel.
- Story 1: in Hosted Test the panel reaches the unlinked or linked state, never
  the "not configured" error.
- Story 2: the console's Allowlist for URL Fetching Domains contains
  https://kana-cards.com.
- Story 2: no other external domain is fetched by the Extension frontend (no
  other allowlist entry needed) — confirmed in Hosted Test dev tools.
- Story 2: in Hosted Test the browser console shows no CSP connect-src
  violation when the panel calls /twitch/status.
- Story 2: the submission checklist lists the allowlist step before "Submit"
  (reviewed by the operator alongside the console action).
- Story 4: confirming an MVP in Hosted Test posts a chat message in the live
  channel matching the listing description wording.
"""
import pathlib
import re
import shutil
import subprocess
from html.parser import HTMLParser

import pytest

# backend/tests/ -> backend/ -> repo root
REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
EXT_DIR = REPO_ROOT / "twitch-extension"
PACKAGE_SH = EXT_DIR / "package.sh"
SUBMISSION_DOC = (
    REPO_ROOT / "markdown" / "features" / "reference" / "twitch-extension-review-submission.md"
)
PACKAGED_HTML = ["panel.html", "config.html", "live_config.html"]
TWITCH_HELPER_URL = "https://extension-files.twitch.tv/helper/v1/twitch-ext.min.js"



class _RefParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.refs = []
        self.scripts = []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        for key in ("src", "href"):
            if a.get(key):
                self.refs.append(a[key])
        if tag == "script":
            self.scripts.append(a.get("src"))


def _parse(html_text):
    p = _RefParser()
    p.feed(html_text)
    return p


def _package_files():
    m = re.search(r"FILES=\(([^)]*)\)", PACKAGE_SH.read_text())
    assert m, "FILES=(...) array not found in package.sh"
    return [line.split("#")[0].strip() for line in m.group(1).splitlines() if line.split("#")[0].strip()]


def _is_local(ref):
    return not re.match(r"^((https?:)?//|#|data:|mailto:)", ref)


def _unpackaged_refs(html_text, files):
    return [r for r in _parse(html_text).refs if _is_local(r) and r not in files]


def _first_script_is_helper(html_text):
    scripts = _parse(html_text).scripts
    return bool(scripts) and scripts[0] == TWITCH_HELPER_URL


def _require_zip():
    if shutil.which("zip") is None:
        pytest.skip("zip is not installed")


def _ext_copy(tmp_path):
    dest = tmp_path / "twitch-extension"
    shutil.copytree(EXT_DIR, dest, ignore=shutil.ignore_patterns("*.zip"))
    return dest


def _run_package(ext_dir, *args):
    return subprocess.run(
        ["bash", str(ext_dir / "package.sh"), *args],
        capture_output=True, text=True, timeout=60,
    )


def _submission_doc():
    return SUBMISSION_DOC.read_text()


def _description_block():
    doc = _submission_doc()
    start = doc.index("**Description** (full):")
    end = doc.index("This wording is deliberately", start)
    return doc[start:end]


def _chat_paragraph():
    block = _description_block()
    start = block.index("**Twitch Chat:**")
    lines = []
    for line in block[start:].splitlines():
        stripped = line.lstrip("> ").strip()
        if not stripped:
            break
        lines.append(stripped)
    return " ".join(lines)


def _unlinked_view(panel_text):
    m = re.search(r'<div id="view-unlinked">(.*?)<div id="view-linked"', panel_text, re.S)
    assert m, "view-unlinked element not found in panel.html"
    return m.group(1)


def _linked_view(panel_text):
    m = re.search(r'<div id="view-linked"[^>]*>(.*?)<!-- Winner', panel_text, re.S)
    assert m, "view-linked element not found in panel.html"
    return m.group(1)


# ---------------------------------------------------------------------------
# Story 1 — Reviewer Can Load Every Extension View (version bump)
# ---------------------------------------------------------------------------

def test_submission_doc_references_version_1_1_6():
    """The submitted zip version is higher than 1.1.5: the submission doc header and checklist reference 1.1.6."""
    doc = _submission_doc()
    header = doc.split("## Submission checklist")[0]
    checklist = doc.split("## Submission checklist")[1].split("## Listing copy")[0]
    assert "twitch-extension-1.1.6.zip" in header
    assert "1.1.6" in checklist


def test_submission_doc_does_not_submit_version_1_1_5():
    """The submission doc no longer names twitch-extension-1.1.5.zip as the version to upload (1.1.5 only kept as the XSS-fix note)."""
    doc = _submission_doc()
    assert "twitch-extension-1.1.5.zip" not in doc
    checklist = doc.split("## Submission checklist")[1].split("## Listing copy")[0]
    assert "1.1.5" not in checklist
    assert "1.1.5" in doc  # kept as the XSS-fix note


# ---------------------------------------------------------------------------
# Story 3 — Package Self-Check Before Upload (package.sh, run in tmp copy)
# ---------------------------------------------------------------------------

def test_package_sh_valid_version_exits_zero_and_creates_zip(tmp_path):
    """On a clean tmp copy of twitch-extension/, `bash package.sh 9.9.9` exits 0 and creates twitch-extension-9.9.9.zip in the copy only."""
    _require_zip()
    ext = _ext_copy(tmp_path)
    result = _run_package(ext, "9.9.9")
    assert result.returncode == 0, result.stdout + result.stderr
    assert (ext / "twitch-extension-9.9.9.zip").is_file()
    assert not (EXT_DIR / "twitch-extension-9.9.9.zip").exists()


def test_package_sh_success_prints_asset_hosting_paths(tmp_path):
    """On success, package.sh prints the exact console Asset Hosting paths: panel.html, config.html, live_config.html."""
    _require_zip()
    ext = _ext_copy(tmp_path)
    result = _run_package(ext, "9.9.9")
    assert result.returncode == 0, result.stdout + result.stderr
    assert re.search(r"Panel Viewer Path:\s+panel\.html\b", result.stdout)
    assert re.search(r"Config Path:\s+config\.html\b", result.stdout)
    assert re.search(r"Live Config Path:\s+live_config\.html\b", result.stdout)


def test_package_sh_success_prints_fetch_allowlist_entry(tmp_path):
    """On success, package.sh prints the URL Fetching allowlist entry https://kana-cards.com."""
    _require_zip()
    ext = _ext_copy(tmp_path)
    result = _run_package(ext, "9.9.9")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "Allowlist for URL Fetching Domains" in result.stdout
    assert "https://kana-cards.com" in result.stdout


def test_package_sh_no_version_argument_exits_nonzero(tmp_path):
    """package.sh exits non-zero with a usage message when no version argument is given, instead of defaulting to 1.0.0 (and creates no zip)."""
    ext = _ext_copy(tmp_path)
    result = _run_package(ext)
    assert result.returncode != 0
    assert "Usage" in result.stdout + result.stderr
    assert list(ext.glob("*.zip")) == []


def test_package_sh_existing_zip_exits_nonzero(tmp_path):
    """package.sh exits non-zero with an 'already exists' message if the output zip exists, and leaves the existing zip unmodified."""
    ext = _ext_copy(tmp_path)
    existing = ext / "twitch-extension-9.9.9.zip"
    existing.write_bytes(b"previously submitted")
    result = _run_package(ext, "9.9.9")
    assert result.returncode != 0
    assert "already exists" in result.stdout + result.stderr
    assert existing.read_bytes() == b"previously submitted"


def test_package_sh_missing_local_reference_exits_nonzero_naming_file(tmp_path):
    """If a packaged HTML file references a local file not in FILES (e.g. <script src="missing.js">), package.sh exits non-zero and names missing.js."""
    ext = _ext_copy(tmp_path)
    panel = ext / "panel.html"
    panel.write_text(panel.read_text().replace("</body>", '<script src="missing.js"></script>\n</body>'))
    result = _run_package(ext, "9.9.9")
    assert result.returncode != 0
    assert "missing.js" in result.stdout + result.stderr
    assert not (ext / "twitch-extension-9.9.9.zip").exists()


def test_package_sh_absolute_urls_not_treated_as_missing(tmp_path):
    """External http(s):// and protocol-relative // references (e.g. the Twitch helper) do not trigger the missing-file check."""
    _require_zip()
    ext = _ext_copy(tmp_path)
    panel = ext / "panel.html"
    panel.write_text(panel.read_text().replace(
        "</body>",
        '<script src="//cdn.example.com/lib.js"></script>\n'
        '<link rel="stylesheet" href="http://example.com/x.css">\n</body>',
    ))
    result = _run_package(ext, "9.9.9")
    assert result.returncode == 0, result.stdout + result.stderr
    assert TWITCH_HELPER_URL in panel.read_text()
    assert "extension-files.twitch.tv" not in result.stdout + result.stderr


# ---------------------------------------------------------------------------
# Story 3 — Static package test (HTML references vs package.sh FILES)
# ---------------------------------------------------------------------------

def test_package_files_contain_every_local_html_asset():
    """Every non-absolute src/href in panel.html, config.html and live_config.html is in package.sh's FILES list."""
    files = _package_files()
    for name in PACKAGED_HTML:
        assert name in files
        assert _unpackaged_refs((EXT_DIR / name).read_text(), files) == [], name


def test_package_files_check_flags_unpackaged_reference():
    """The static reference check reports a local reference absent from FILES (e.g. injected missing.js) by name."""
    files = _package_files()
    html = (EXT_DIR / "panel.html").read_text().replace(
        "</body>", '<script src="missing.js"></script></body>'
    )
    assert _unpackaged_refs(html, files) == ["missing.js"]


def test_html_first_script_is_twitch_helper():
    """The Twitch helper script is the first <script> in panel.html, config.html and live_config.html."""
    for name in PACKAGED_HTML:
        assert _first_script_is_helper((EXT_DIR / name).read_text()), name


def test_html_first_script_not_helper_is_detected():
    """An HTML file whose first <script> is a local script (helper later or absent) fails the helper-first check."""
    helper_later = (
        '<html><head><script src="extension.js"></script>'
        f'<script src="{TWITCH_HELPER_URL}"></script></head></html>'
    )
    helper_absent = '<html><head><script src="extension.js"></script></head></html>'
    assert not _first_script_is_helper(helper_later)
    assert not _first_script_is_helper(helper_absent)


def test_package_files_exclude_dev_harness_and_package_sh():
    """dev-harness.html and package.sh are not in package.sh's FILES list."""
    files = _package_files()
    assert "dev-harness.html" not in files
    assert "package.sh" not in files


# ---------------------------------------------------------------------------
# Story 4 — Chat Usage Disclosed in Listing
# ---------------------------------------------------------------------------

def test_listing_description_has_twitch_chat_paragraph():
    """The listing description in twitch-extension-review-submission.md has a dedicated Twitch Chat paragraph: one message when the broadcaster confirms a match MVP, nothing else."""
    para = _chat_paragraph().lower()
    assert "one message" in para
    assert "confirms a match mvp" in para
    assert "posts nothing else" in para


def test_listing_description_states_message_contents():
    """The chat paragraph states the message contents: MVP player name, Kanaliiga Fantasy usernames of drop winners, or a note when no linked viewers were in the pool."""
    para = _chat_paragraph()
    assert "Match MVP: PlayerName!" in para
    assert "Kanaliiga Fantasy usernames" in para
    assert "no linked viewers" in para.lower()


def test_listing_description_states_no_chat_read_store_or_repeat_drop():
    """The chat paragraph states the Extension never reads, stores or moderates chat, and re-selecting the MVP does not trigger a second token drop."""
    para = _chat_paragraph().lower()
    assert re.search(r"never reads, stores or moderates chat", para)
    assert "does not drop tokens again" in para


def test_listing_chat_paragraph_is_inside_description_block():
    """The chat disclosure sits inside the Description block the operator pastes into the listing, not only elsewhere in the doc."""
    block = _description_block()
    assert "**Twitch Chat:**" in block
    chat_line = next(l for l in block.splitlines() if "**Twitch Chat:**" in l)
    assert chat_line.startswith(">")


def test_config_html_mentions_chat_announcement():
    """config.html's broadcaster copy mentions the MVP chat announcement, consistent with the listing description."""
    text = (EXT_DIR / "config.html").read_text()
    broadcaster = text.split("For broadcasters", 1)[1].split("<h3", 1)[0]
    assert "chat announcement" in broadcaster
    assert "Kanaliiga Fantasy usernames" in broadcaster


def test_panel_html_unlinked_view_mentions_username_in_chat():
    """panel.html's unlinked view tells viewers that linking can show their Kanaliiga username in chat if they win a drop."""
    unlinked = _unlinked_view((EXT_DIR / "panel.html").read_text())
    assert "Kanaliiga Fantasy username" in unlinked
    assert "chat" in unlinked


def test_panel_html_chat_note_not_only_in_linked_view():
    """The panel chat note is in the unlinked view element, not solely in the linked view (where unlinked viewers would never see it)."""
    text = (EXT_DIR / "panel.html").read_text()
    assert 'id="chat-note"' in _unlinked_view(text)
    assert "chat-note" not in _linked_view(text)
