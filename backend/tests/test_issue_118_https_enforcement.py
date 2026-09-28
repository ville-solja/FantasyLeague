"""
Tests for plan-issue-118-https-enforcement.md (resolves GitHub issue #118).

Session cookies only get the `Secure` flag when HTTPS_ONLY=true is set, and a
default deployment is HTTP-only. The plan adds a startup check that refuses to
start without HTTPS_ONLY=true (unless a local-dev bypass is set) and makes the
requirement prominent in the docs. One test per acceptance criterion (happy
path plus the primary failure path for each story).

Testing approach per story:

  Story 1 — Fail Loudly at Startup if HTTPS Isn't Enforced
    - The check runs at module import time in backend/main.py, next to the
      existing SECRET_KEY / ENV=production guards (issue #136). Run
      `import main` in a subprocess with a controlled environment (pattern:
      `_run_import_main` in test_issue_136_security_audit_3.py) so module-level
      state stays isolated from the rest of the suite.
    - The helper strips ENV, DEBUG, TWITCH_LOCAL_DEV, SECRET_KEY, HTTPS_ONLY and
      AUTO_INGEST_LEAGUES from the inherited env, and points DATABASE_URL at a
      tmp_path SQLite file. Pass SECRET_KEY explicitly (32+ chars) so the
      SECRET_KEY guard never fires first and masks the HTTPS_ONLY result.
    - "Refuses to start" means non-zero returncode with "RuntimeError" and
      "HTTPS_ONLY" in stderr.
    - Outside ENV=production the dev bypasses (DEBUG=true, TWITCH_LOCAL_DEV=true)
      skip the check. Under ENV=production the #136 guard already forbids dev
      flags, so ENV=production + HTTPS_ONLY unset must always fail.
    - CI: .github/workflows/ui-tests.yml starts the real server via docker
      compose with a generated .env. Static text check (PyYAML is not a
      dependency; see lessons-learned 2026-09-28) that its "Start app" step
      sets HTTPS_ONLY=true or a dev bypass (DEBUG=true / TWITCH_LOCAL_DEV=true).

  Story 2 — Prominent Deployment Documentation
    - Static checks of README.md (the `## Deployment` section only, up to the
      next `## ` heading), .env.example (the comment block directly above the
      `HTTPS_ONLY` line), and markdown/features/reference/https-enforcement.md.

Manual verification (not automated):
  - Before deploying: HTTPS_ONLY=true is set on the live deployment AND the
    app is actually behind a TLS-terminating proxy (otherwise browsers drop
    the Secure cookie and login breaks).
"""
import os
import pathlib
import subprocess
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

_BACKEND_DIR = pathlib.Path(__file__).resolve().parent.parent
_REPO_ROOT = _BACKEND_DIR.parent

_PROD_SECRET = "x" * 40
_STRIPPED_ENV = (
    "ENV", "DEBUG", "TWITCH_LOCAL_DEV", "SECRET_KEY", "HTTPS_ONLY", "AUTO_INGEST_LEAGUES",
)


def _read(rel_path):
    return (_REPO_ROOT / rel_path).read_text(encoding="utf-8")


def _run_import_main(tmp_path, env_overrides):
    """Run `import main` in a subprocess with a controlled environment."""
    env = {k: v for k, v in os.environ.items() if k not in _STRIPPED_ENV}
    env["DATABASE_URL"] = f"sqlite:///{tmp_path / 'fantasy.db'}"
    env["SECRET_KEY"] = _PROD_SECRET
    env.update(env_overrides)
    return subprocess.run(
        [sys.executable, "-c", "import main"],
        cwd=str(_BACKEND_DIR), env=env, capture_output=True, text=True, timeout=120,
    )


def _assert_https_only_refusal(result):
    assert result.returncode != 0, "main imported cleanly but should refuse to start"
    assert "RuntimeError" in result.stderr
    assert "HTTPS_ONLY" in result.stderr


def _readme_deployment_section():
    readme = _read("README.md")
    assert "\n## Deployment" in readme
    return readme.split("\n## Deployment", 1)[1].split("\n## ", 1)[0]


def _env_example_https_only_comment():
    """The comment block directly above the `# HTTPS_ONLY=` line, joined into one line of text."""
    lines = _read(".env.example").splitlines()
    idx = next(i for i, line in enumerate(lines) if line.lstrip("# ").startswith("HTTPS_ONLY="))
    block = []
    for line in reversed(lines[:idx]):
        if not line.startswith("#"):
            break
        block.insert(0, line)
    assert block, "no comment above HTTPS_ONLY in .env.example"
    return " ".join(line.lstrip("#").strip() for line in block)


# ---------------------------------------------------------------------------
# Story 1 — Fail Loudly at Startup if HTTPS Isn't Enforced
# ---------------------------------------------------------------------------

def test_startup_https_only_true_starts(tmp_path):
    """HTTPS_ONLY=true with no dev bypass imports main cleanly (subprocess)."""
    result = _run_import_main(tmp_path, {"HTTPS_ONLY": "true"})
    assert result.returncode == 0, result.stderr


def test_startup_https_only_unset_no_bypass_raises_runtime_error(tmp_path):
    """HTTPS_ONLY unset and neither DEBUG=true nor TWITCH_LOCAL_DEV=true: import main raises RuntimeError naming HTTPS_ONLY."""
    result = _run_import_main(tmp_path, {})
    _assert_https_only_refusal(result)


def test_startup_https_only_false_no_bypass_raises_runtime_error(tmp_path):
    """HTTPS_ONLY=false (any value other than "true") with no dev bypass also refuses to start."""
    for value in ("false", "1", "yes", ""):
        result = _run_import_main(tmp_path, {"HTTPS_ONLY": value})
        _assert_https_only_refusal(result)


def test_startup_https_only_error_message_is_actionable(tmp_path):
    """The RuntimeError says to set HTTPS_ONLY=true behind a TLS-terminating reverse proxy, or use DEBUG=true / TWITCH_LOCAL_DEV=true in local dev."""
    result = _run_import_main(tmp_path, {})
    _assert_https_only_refusal(result)
    err = result.stderr
    assert "HTTPS_ONLY=true" in err
    assert "TLS-terminating reverse proxy" in err
    assert "DEBUG=true" in err and "TWITCH_LOCAL_DEV=true" in err


def test_startup_https_only_unset_debug_bypass_starts(tmp_path):
    """Outside ENV=production, DEBUG=true skips the HTTPS_ONLY check and main imports cleanly."""
    result = _run_import_main(tmp_path, {"DEBUG": "true"})
    assert result.returncode == 0, result.stderr


def test_startup_https_only_unset_twitch_local_dev_bypass_starts(tmp_path):
    """Outside ENV=production, TWITCH_LOCAL_DEV=true skips the HTTPS_ONLY check and main imports cleanly."""
    # SECRET_KEY must be unset: the lifespan (not run here) rejects TWITCH_LOCAL_DEV with a
    # real SECRET_KEY, and the import-time checks are what this test covers.
    env = {"TWITCH_LOCAL_DEV": "true", "SECRET_KEY": ""}
    result = _run_import_main(tmp_path, env)
    assert result.returncode == 0, result.stderr


def test_startup_env_production_https_only_unset_fails(tmp_path):
    """ENV=production with a valid SECRET_KEY but HTTPS_ONLY unset refuses to start."""
    result = _run_import_main(tmp_path, {"ENV": "production"})
    _assert_https_only_refusal(result)


def test_startup_env_production_https_only_true_starts(tmp_path):
    """ENV=production with a valid SECRET_KEY and HTTPS_ONLY=true starts cleanly."""
    result = _run_import_main(tmp_path, {"ENV": "production", "HTTPS_ONLY": "true"})
    assert result.returncode == 0, result.stderr


def test_existing_suite_env_has_dev_bypass_for_main_import():
    """The test suite imports main with a dev bypass in effect (conftest sets DEBUG=true), so the new check does not block collection."""
    conftest = (_BACKEND_DIR / "tests" / "conftest.py").read_text(encoding="utf-8")
    assert 'os.environ.setdefault("DEBUG", "true")' in conftest
    before_imports = conftest.split("from database import", 1)[0]
    assert 'setdefault("DEBUG", "true")' in before_imports
    assert os.environ.get("DEBUG", "").lower() == "true" or os.environ.get("HTTPS_ONLY", "").lower() == "true"


def test_ui_tests_workflow_start_app_sets_https_only_or_dev_bypass():
    """.github/workflows/ui-tests.yml "Start app" step writes HTTPS_ONLY=true or a dev bypass (DEBUG=true / TWITCH_LOCAL_DEV=true) into .env, so CI can start the server."""
    workflow = _read(".github/workflows/ui-tests.yml")
    assert "- name: Start app" in workflow
    step = workflow.split("- name: Start app", 1)[1].split("- name:", 1)[0]
    assert ".env" in step
    assert any(flag in step for flag in ("HTTPS_ONLY=true", "DEBUG=true", "TWITCH_LOCAL_DEV=true"))


# ---------------------------------------------------------------------------
# Story 2 — Prominent Deployment Documentation
# ---------------------------------------------------------------------------

def test_readme_deployment_section_requires_tls_reverse_proxy_and_https_only():
    """README.md `## Deployment` section states production must run behind a TLS-terminating reverse proxy with HTTPS_ONLY=true."""
    section = _readme_deployment_section()
    assert "TLS-terminating reverse proxy" in section
    assert "HTTPS_ONLY=true" in section


def test_readme_deployment_section_mentions_startup_refusal_not_passing_mention():
    """README.md Deployment section has a dedicated HTTPS subsection saying the app refuses to start without HTTPS_ONLY=true (not only mentioned elsewhere)."""
    section = _readme_deployment_section()
    assert "### Production requires HTTPS" in section
    sub = section.split("### Production requires HTTPS", 1)[1].split("\n### ", 1)[0]
    assert "refuses to start" in sub
    assert "HTTPS_ONLY=true" in sub


def test_env_example_https_only_comment_says_required_in_production():
    """.env.example comment above HTTPS_ONLY says it must be set in production and the app refuses to start without it."""
    comment = _env_example_https_only_comment()
    assert "Must be set in production" in comment
    assert "refuses" in comment and "start" in comment


def test_env_example_https_only_comment_not_framed_as_optional_default():
    """.env.example HTTPS_ONLY comment no longer reads as optional ("Defaults to false" framing removed)."""
    comment = _env_example_https_only_comment()
    assert "Defaults to false" not in comment
    assert "default" not in comment.lower()


def test_https_enforcement_reference_doc_explains_vulnerability_and_startup_check():
    """markdown/features/reference/https-enforcement.md explains the cookie-interception risk, the startup check and its dev bypasses."""
    doc = _read("markdown/features/reference/https-enforcement.md")
    assert "Secure" in doc and "intercept" in doc
    assert "RuntimeError" in doc
    assert "DEBUG=true" in doc and "TWITCH_LOCAL_DEV=true" in doc
    assert "ENV=production" in doc


def test_https_enforcement_reference_doc_has_no_planned_markers():
    """markdown/features/reference/https-enforcement.md is filled in (no "*(planned)*" markers) and is linked from markdown/features/README.md."""
    doc = _read("markdown/features/reference/https-enforcement.md")
    assert "*(planned)*" not in doc
    index = _read("markdown/features/README.md")
    assert "reference/https-enforcement.md" in index
