"""
Tests for plan-issue-236-cve-2026-111497-brotli.md (resolves GitHub issue #236).

CVE-2026-111497 is a buffer overflow in Google Brotli's decoder (1.0.3 - 1.2.0,
fixed in 1.0.10, 1.1.1, 1.2.1). The only vulnerable copy in the image is
Pillow's bundled libbrotlidec 1.2.0, reachable only through WOFF2 font loading,
which never runs. These guards keep that verdict true, and the doc checks pin
the analysis in markdown/features/reference/vulnerability-analyses.md.

  Story 1: The Operator Knows Whether the CVE Affects Production (doc checks)
  Story 2: Brotli Stays Unreachable Until Fixed Versions Ship (guards + negatives)
  Story 3: Fixed Versions Are Picked Up (Dependency Scout, base image state)

Approach notes (for the developer filling these in):

- All checks are static: read files from disk, never the network, never the DB.
  Paths: BACKEND = Path(__file__).resolve().parents[1]; REPO = BACKEND.parent.
- Put the guard logic in small pure helpers in this file so the negative
  tests can feed them fake input:
    font_path_problems(paths: list[str]) -> list[str]
        One message per entry that is not an absolute path under
        /usr/share/fonts/ ending in ".ttf" (case-sensitive suffix check;
        reject "..", relative paths, ".woff2", ".woff", ".otf", ".ttc").
    truetype_call_sites(sources: dict[str, str]) -> list[str]
        `sources` maps a relative module path ("image.py", "routers/x.py") to
        its source text. Use `ast` to find every call whose func is the
        attribute `truetype` (ImageFont.truetype, or any alias `.truetype`) and
        also any `from PIL.ImageFont import truetype` import. Report every
        site that is not inside the function `_get_font` in "image.py".
    brotli_requirement_problems(lines: list[str]) -> list[str]
        Report any requirement line whose project name, normalised per PEP 503
        (lowercase, runs of -_. -> "-"), is "brotli" or "brotlicffi". Ignore
        comments and blank lines; handle extras/markers/specifiers
        ("Brotli[foo]>=1.0 ; python_version>'3'").
    brotli_version_problems(versions: dict[str, str | None]) -> list[str]
        `versions` maps "brotli"/"brotlicffi" to an installed version string
        or None (not installed). Report any installed version below 1.2.1
        (compare with packaging.version.Version; treat unparsable as a problem).
- The real-environment tests collect module sources with
  BACKEND.rglob("*.py") excluding tests/, .venv/, venv/ and site-packages, and
  read versions with importlib.metadata.version (PackageNotFoundError -> None).
- Doc checks read the analysis doc and CLAUDE.md as text; match phrases
  case-insensitively and allow either backticked or plain commands.
"""

import ast
import importlib.metadata
import posixpath
import re
from pathlib import Path

from packaging.version import InvalidVersion, Version

BACKEND = Path(__file__).resolve().parents[1]
REPO = BACKEND.parent
DOC = REPO / "markdown" / "features" / "reference" / "vulnerability-analyses.md"
CLAUDE_MD = REPO / "CLAUDE.md"
FEATURES_README = REPO / "markdown" / "features" / "README.md"
REQUIREMENTS = BACKEND / "requirements.txt"
DOCKERFILE = REPO / "Dockerfile"

CVE = "CVE-2026-111497"
FONT_ROOT = "/usr/share/fonts/"
BROTLI_PROJECTS = ("brotli", "brotlicffi")
BROTLI_FIXED = Version("1.2.1")
_SKIP_DIRS = {"tests", ".venv", "venv", "site-packages", "node_modules", "__pycache__"}


# ---------------------------------------------------------------------------
# Guard helpers (pure, so the negative tests can feed them fake input)
# ---------------------------------------------------------------------------

def font_path_problems(paths):
    problems = []
    for p in paths:
        if not isinstance(p, str):
            problems.append(f"font path is not a string: {p!r}")
            continue
        if not p.startswith("/"):
            problems.append(f"font path is not absolute: {p}")
        elif ".." in p.split("/") or posixpath.normpath(p) != p:
            problems.append(f"font path is not normalised: {p}")
        elif not p.startswith(FONT_ROOT):
            problems.append(f"font path is outside {FONT_ROOT}: {p}")
        elif not p.endswith(".ttf"):
            problems.append(f"font path is not a .ttf file: {p}")
    return problems


def truetype_call_sites(sources):
    problems = []
    for rel, src in sources.items():
        tree = ast.parse(src, filename=rel)
        allowed = set()
        if rel == "image.py":
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == "_get_font":
                    allowed.update(id(n) for n in ast.walk(node))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module and node.module.endswith("ImageFont"):
                if any(a.name in FONT_LOADERS + ("*",) for a in node.names):
                    problems.append(f"{rel}:{node.lineno}: imports a font loader directly")
            elif isinstance(node, ast.Attribute) and node.attr in FONT_LOADERS:
                # Any other way to load a font file (FreeTypeFont, font_variant) is refused
                # everywhere; truetype only inside image._get_font (security review Low 1).
                if not (node.attr == "truetype" and id(node) in allowed):
                    problems.append(f"{rel}:{node.lineno}: {node.attr} used outside image._get_font")
            elif (isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "getattr"
                  and node.args and isinstance(node.args[0], ast.Name) and node.args[0].id == "ImageFont"):
                problems.append(f"{rel}:{node.lineno}: getattr(ImageFont, ...) hides a font loader")
    return problems


FONT_LOADERS = ("truetype", "FreeTypeFont", "font_variant")


def get_font_source_problems(src):
    """In image._get_font, truetype's first argument must be the loop variable of a
    `for ... in _FONT_PATHS` loop, so it can only load the fixed font files
    (security review Low 2)."""
    tree = ast.parse(src)
    fn = next((n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "_get_font"), None)
    if fn is None:
        return ["image._get_font not found"]
    loop_vars = {n.target.id for n in ast.walk(fn)
                 if isinstance(n, ast.For) and isinstance(n.target, ast.Name)
                 and isinstance(n.iter, ast.Name) and n.iter.id == "_FONT_PATHS"}
    problems = []
    for n in ast.walk(fn):
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "truetype":
            arg = n.args[0] if n.args else None
            if not (isinstance(arg, ast.Name) and arg.id in loop_vars):
                problems.append(f"line {n.lineno}: truetype() loads something other than a _FONT_PATHS entry")
    return problems


def _requirement_name(line):
    line = line.split("#", 1)[0].strip()
    if not line or line.startswith("-"):
        return None
    m = re.match(r"[A-Za-z0-9][A-Za-z0-9._-]*", line)
    return re.sub(r"[-_.]+", "-", m.group(0)).lower() if m else None


def _requirement_extras(line):
    m = re.match(r"\s*[A-Za-z0-9][A-Za-z0-9._-]*\s*\[([^\]]*)\]", line.split("#", 1)[0])
    return [e.strip().lower() for e in m.group(1).split(",")] if m else []


def brotli_requirement_problems(lines):
    """A requirement naming brotli/brotlicffi, or an extra that pulls one in
    (urllib3[brotli], httpx[brotli], ...; security review Low 3)."""
    problems = []
    for line in lines:
        name = _requirement_name(line)
        if name in BROTLI_PROJECTS:
            problems.append(f"requirement names {name}: {line.strip()}")
        elif any("brotli" in e for e in _requirement_extras(line)):
            problems.append(f"requirement extra pulls in Brotli: {line.strip()}")
    return problems


def brotli_version_problems(versions):
    problems = []
    for name, ver in versions.items():
        if ver is None:
            continue
        try:
            if Version(ver) < BROTLI_FIXED:
                problems.append(f"{name} {ver} is below {BROTLI_FIXED} (CVE-2026-111497)")
        except InvalidVersion:
            problems.append(f"{name} has an unparsable version {ver!r}")
    return problems


def scout_line_problems(text):
    lines = [l for l in text.splitlines() if "Dependency Scout" in l]
    if not lines:
        return ["no Dependency Scout line"]
    line = lines[0]
    low = line.lower()
    problems = []
    if "pillow.libs" not in low and not ("pillow" in low and "bundled native libraries" in low):
        problems.append("Dependency Scout does not check Pillow's bundled libraries")
    if "brotli" not in low:
        problems.append("Dependency Scout does not mention Brotli")
    if "backend/requirements.txt" not in line:
        problems.append("Dependency Scout no longer checks backend/requirements.txt")
    return problems


# ---------------------------------------------------------------------------
# Doc helpers
# ---------------------------------------------------------------------------

def _cve_section():
    text = DOC.read_text(encoding="utf-8")
    m = re.search(rf"^(#+) [^\n]*{CVE}[^\n]*$", text, re.M)
    assert m, f"no heading containing {CVE} in {DOC}"
    level = len(m.group(1))
    rest = text[m.end():]
    nxt = re.search(rf"^#{{1,{level}}} ", rest, re.M)
    return text[m.start(): m.end() + (nxt.start() if nxt else len(rest))]


def _plain(text):
    return text.replace("`", "").replace("\\|", "|")


def _libbrotli1_outcome(section):
    for line in section.splitlines():
        low = line.lower()
        if "libbrotli1:" in low.replace("`", ""):
            for word in ("present", "absent", "pending"):
                if word in low:
                    return word
    return None


def _backend_sources():
    out = {}
    for p in BACKEND.rglob("*.py"):
        rel = p.relative_to(BACKEND)
        if _SKIP_DIRS.intersection(rel.parts):
            continue
        out[rel.as_posix()] = p.read_text(encoding="utf-8")
    return out


# ---------------------------------------------------------------------------
# Story 1: The Operator Knows Whether the CVE Affects Production
# ---------------------------------------------------------------------------

def test_analysis_doc_has_cve_section_with_summary_versions_routes_verdict():
    """The CVE section names the decoder, affected and fixed versions, a route
    table (Pillow, libbrotli1, brotlicffi/urllib3 rows), WOFF2 and the verdict."""
    section = _cve_section()
    low = section.lower()
    assert "decode.c" in section or "decoder" in low
    for v in ("1.0.3", "1.2.0", "1.0.10", "1.1.1", "1.2.1"):
        assert v in section, v
    rows = [l for l in section.splitlines() if l.lstrip().startswith("|")]
    assert any("Pillow" in r for r in rows)
    assert any("libbrotli1" in r for r in rows)
    assert any("brotlicffi" in r or "urllib3" in r for r in rows)
    assert "WOFF2" in section
    assert "not exploitable" in low


def test_analysis_doc_lists_follow_ups_with_triggers():
    """Follow-ups name the Pillow bump with its 1.2.1 trigger and a base-image
    follow-up tied to libbrotli1."""
    section = _cve_section()
    m = re.search(r"^#+ Follow-ups\s*$", section, re.M | re.I)
    assert m, "no Follow-ups part"
    bullets = [l for l in section[m.end():].splitlines() if l.lstrip().startswith("-")]
    assert any("Pillow" in b and "1.2.1" in b for b in bullets)
    assert any("libbrotli1" in b for b in bullets)


def test_analysis_doc_lists_production_check_commands_with_expected_results():
    """The three read-only commands appear, each with an expected result and
    an action if the result differs, in the same table row or bullet."""
    lines = _plain(_cve_section()).splitlines()
    checks = [
        ("docker exec fantasyleague pip show brotli brotlicffi", ("not found",)),
        ("docker exec fantasyleague dpkg -l | grep -i brotli", ("empty",)),
        ("pillow.libs", ("1.2.0",)),
    ]
    for cmd, expected in checks:
        hits = [l for l in lines if cmd in l and "docker exec" in l]
        assert hits, f"command missing: {cmd}"
        line = hits[0].lower()
        assert any(e in line for e in expected), f"no expected result for {cmd}"
        assert re.search(r"\bif\b", line), f"no action-if-different for {cmd}"


def test_analysis_doc_records_production_results_or_pending_state():
    """The production check is recorded as dated results or explicitly as
    pending, and the libbrotli1 outcome is present / absent / pending."""
    section = _cve_section()
    m = re.search(r"^#+ Production check results\s*$", section, re.M | re.I)
    assert m, "no Production check results part"
    rest = section[m.end():]
    nxt = re.search(r"^#+ ", rest, re.M)
    results = rest[: nxt.start() if nxt else len(rest)].lower()
    dated = re.search(r"\b\d{4}-\d{2}-\d{2}\b", results) and ("present" in results or "absent" in results)
    pending = "pending" in results or "not yet run" in results
    assert dated or pending, "production check neither recorded nor marked pending"
    assert _libbrotli1_outcome(section) in ("present", "absent", "pending")


def test_features_readme_links_vulnerability_analyses_doc():
    """The features index links the analysis doc."""
    assert "reference/vulnerability-analyses.md" in FEATURES_README.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Story 2: Brotli Stays Unreachable Until Fixed Versions Ship
# ---------------------------------------------------------------------------

def test_font_paths_are_absolute_ttf_under_usr_share_fonts():
    """image._FONT_PATHS is a non-empty list of absolute .ttf paths under
    /usr/share/fonts/."""
    import image

    paths = list(image._FONT_PATHS)
    assert paths
    assert all(isinstance(p, str) for p in paths)
    assert font_path_problems(paths) == []


def test_font_path_guard_reports_woff2_path():
    """Negative: WOFF2, relative, outside, traversal and .otf paths are reported."""
    woff2 = "/usr/share/fonts/truetype/x/Evil.woff2"
    problems = font_path_problems([woff2])
    assert len(problems) == 1 and woff2 in problems[0]
    for bad in (
        "fonts/Rel.ttf",
        "/tmp/Evil.ttf",
        "/usr/share/fonts/../../tmp/Evil.ttf",
        "/usr/share/fonts/x/Evil.otf",
    ):
        assert len(font_path_problems([bad])) == 1, bad
    assert font_path_problems(["/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"]) == []


def test_truetype_called_only_in_image_get_font():
    """No backend module calls truetype outside image._get_font, and the scan
    finds the known call inside _get_font."""
    sources = _backend_sources()
    assert "image.py" in sources
    assert truetype_call_sites(sources) == []
    tree = ast.parse(sources["image.py"])
    get_font = next(
        n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "_get_font"
    )
    assert any(
        isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "truetype"
        for n in ast.walk(get_font)
    )


def test_truetype_guard_reports_call_outside_get_font():
    """Negative: calls in other modules, outside _get_font, and direct imports
    are reported; the call in _get_font is not."""
    for fake in (
        {"routers/evil.py": "from PIL import ImageFont\nImageFont.truetype(p, 12)"},
        {"image.py": "def other():\n    ImageFont.truetype(p, 1)"},
        {"x.py": "from PIL.ImageFont import truetype"},
    ):
        assert len(truetype_call_sites(fake)) == 1, fake
    ok = {"image.py": "def _get_font(size):\n    return ImageFont.truetype(p, size)"}
    assert truetype_call_sites(ok) == []


def test_requirements_do_not_name_brotli_or_brotlicffi():
    """backend/requirements.txt names neither brotli nor brotlicffi."""
    lines = REQUIREMENTS.read_text(encoding="utf-8").splitlines()
    assert brotli_requirement_problems(lines) == []


def test_brotli_requirement_guard_reports_fake_requirement_line():
    """Negative: Brotli requirement lines are reported in any spelling."""
    for bad in (
        "brotli==1.1.0",
        "Brotli>=1.0",
        "brotlicffi",
        "brotli[ffi] ; python_version > '3'",
        "BrotliCFFI~=1.1",
    ):
        assert len(brotli_requirement_problems([bad])) == 1, bad
    for ok in ("# brotli is not used", "", "pillow>=13.0.0,<14.0", "brotlipy-unrelated-name==1.0"):
        assert brotli_requirement_problems([ok]) == [], ok


def _distro_managed(dist):
    """Installed by the OS package manager (Debian/Ubuntu python3-brotli), not
    pip: its version string doesn't reflect distro security backports, and the
    app's environments (CI, the python:3.11-slim image) never see dist-packages."""
    return dist.read_text("INSTALLER") is None and "dist-packages" in str(dist.locate_file(""))


def _installed_brotli_versions():
    versions = {}
    for name in BROTLI_PROJECTS:
        try:
            dist = importlib.metadata.distribution(name)
        except importlib.metadata.PackageNotFoundError:
            versions[name] = None
            continue
        versions[name] = None if _distro_managed(dist) else dist.version
    return versions


def test_installed_brotli_packages_are_absent_or_fixed():
    """brotli / brotlicffi installed by pip (the app's requirement set) are
    absent or at 1.2.1 or later. Distro-managed copies on a developer machine
    are ignored (see _distro_managed)."""
    assert brotli_version_problems(_installed_brotli_versions()) == []


def test_brotli_version_guard_reports_fake_old_version():
    """Negative: old or unparsable versions are reported; fixed or absent are not."""
    problems = brotli_version_problems({"brotli": "1.2.0", "brotlicffi": None})
    assert len(problems) == 1 and "brotli" in problems[0] and "1.2.0" in problems[0]
    problems = brotli_version_problems({"brotli": None, "brotlicffi": "1.1.0.0"})
    assert len(problems) == 1 and "brotlicffi" in problems[0]
    assert len(brotli_version_problems({"brotli": "not-a-version", "brotlicffi": None})) == 1
    assert brotli_version_problems({"brotli": "1.2.1", "brotlicffi": "1.3.0"}) == []
    assert brotli_version_problems({"brotli": None, "brotlicffi": None}) == []


# ---------------------------------------------------------------------------
# Story 3: Fixed Versions Are Picked Up
# ---------------------------------------------------------------------------

def test_claude_md_dependency_scout_checks_pillow_bundled_libraries():
    """The Dependency Scout line under Scheduled Jobs covers pillow.libs and
    Brotli and still checks backend/requirements.txt."""
    text = CLAUDE_MD.read_text(encoding="utf-8")
    m = re.search(r"^## Scheduled Jobs\s*$", text, re.M)
    assert m, "no Scheduled Jobs section"
    rest = text[m.end():]
    nxt = re.search(r"^## ", rest, re.M)
    section = rest[: nxt.start() if nxt else len(rest)]
    assert scout_line_problems(section) == []


def test_claude_md_dependency_scout_line_without_pillow_libs_is_reported():
    """Negative: the old scout line, and a missing line, are reported."""
    old = (
        "- **Dependency Scout** (`/schedule weekly dep check on Monday mornings`): check every pin in "
        "`backend/requirements.txt` against PyPI and flag outdated or security-relevant versions."
    )
    problems = scout_line_problems(old)
    assert any("Pillow" in p for p in problems)
    assert any("Brotli" in p for p in problems)
    assert scout_line_problems("## Scheduled Jobs\n\n- **Issue Crawler**: ...") == ["no Dependency Scout line"]


def test_dockerfile_matches_recorded_libbrotli1_outcome():
    """The Dockerfile matches the recorded libbrotli1 outcome; the upgrade is
    required only when libbrotli1 is present."""
    section = _cve_section()
    low = _plain(section).lower()
    outcome = _libbrotli1_outcome(section)
    dockerfile = DOCKERFILE.read_text(encoding="utf-8")
    if outcome == "present":
        assert "apt-get upgrade -y" in dockerfile
        assert re.search(r"libbrotli1[^\n]*\d+\.\d+\.\d+", section), "rebuilt libbrotli1 version not recorded"
    elif outcome == "absent":
        assert "no dockerfile change" in low or "dockerfile is unchanged" in low
    else:
        assert outcome == "pending"
        assert any(
            "apt-get upgrade" in l and re.search(r"\bif\b", l) for l in low.splitlines()
        ), "doc does not state the Dockerfile change is conditional"


# ---------------------------------------------------------------------------
# Security review Lows (change review of issue 236)
# ---------------------------------------------------------------------------

def test_font_loader_guard_reports_other_loaders():
    """FreeTypeFont, font_variant and getattr(ImageFont, ...) are reported anywhere."""
    probs = truetype_call_sites({
        "a.py": "from PIL import ImageFont\nf = ImageFont.FreeTypeFont('x.woff2', 10)\n",
        "b.py": "def f(font):\n    return font.font_variant(font='y.woff2')\n",
        "c.py": "from PIL import ImageFont\nload = getattr(ImageFont, 'truetype')\n",
    })
    assert any("a.py" in p and "FreeTypeFont" in p for p in probs)
    assert any("b.py" in p and "font_variant" in p for p in probs)
    assert any("c.py" in p and "getattr" in p for p in probs)


def test_get_font_loads_only_font_paths_entries():
    """image._get_font passes truetype only the loop variable over _FONT_PATHS."""
    src = (BACKEND / "image.py").read_text()
    assert get_font_source_problems(src) == []


def test_get_font_source_guard_reports_other_argument():
    """A truetype call on a parameter or BytesIO is reported."""
    bad = ("def _get_font(size, data):\n"
           "    for path in _FONT_PATHS:\n"
           "        pass\n"
           "    return ImageFont.truetype(BytesIO(data), size)\n")
    assert get_font_source_problems(bad)


def test_brotli_requirement_guard_reports_extras():
    """Extras that pull in Brotli are reported; unrelated extras are not."""
    assert brotli_requirement_problems(["urllib3[brotli]>=2"])
    assert brotli_requirement_problems(["httpx[http2, brotli]"])
    assert not brotli_requirement_problems(["uvicorn[standard]>=0.32"])
