"""
Tests for plan-issue-96-container-health-check.md (resolves GitHub issue #96).

  Story: Evaluate Container Health-Check Options — documentation-only, file-content
    assertions against markdown/features/reference/container-health-check.md (mirrors
    test_frontend_framework_evaluation.py's pattern)
  Story: Implement the Recommended Health Check — approved and implemented: GET /health
    now checks DB connectivity, backend/Dockerfile carries a Python-based HEALTHCHECK
    instruction (no curl dependency), and docker-compose.yml's healthcheck matches.

Run with: cd backend && python -m pytest tests/test_issue_96_container_health_check.py -v
"""

import os

import pytest

_REPO_ROOT = os.path.join(os.path.dirname(__file__), "..", "..")
_DOC_PATH = os.path.join(_REPO_ROOT, "markdown", "features", "reference",
                          "container-health-check.md")
_COMMANDS_DOC_PATH = os.path.join(_REPO_ROOT, "markdown", "features", "reference",
                                  "commands.md")
_MAIN_PY_PATH = os.path.join(_REPO_ROOT, "backend", "main.py")
_DOCKERFILE_PATH = os.path.join(_REPO_ROOT, "Dockerfile")
_COMPOSE_PATH = os.path.join(_REPO_ROOT, "docker-compose.yml")


def _read(path: str) -> str:
    with open(path) as f:
        return f.read()


def _read_doc() -> str:
    return _read(_DOC_PATH)


# ===========================================================================
# Story: Evaluate Container Health-Check Options
# ===========================================================================

class TestContainerHealthCheckEvaluationDocument:
    def test_evaluation_doc_exists_at_expected_path(self):
        """The document lives at markdown/features/reference/container-health-check.md."""
        assert os.path.isfile(_DOC_PATH)

    def test_evaluation_doc_inventories_current_state(self):
        """Doc inventories the current state: GET /health's unconditional {"status": "ok"},
        the docker-compose.yml healthcheck block (test/interval/timeout/retries/start_period),
        and whether docker-compose.dev.yml inherits it via Compose file merge."""
        doc = _read_doc()
        assert '"status": "ok"' in doc
        assert "GET /health" in doc
        for field in ("test:", "interval:", "timeout:", "retries:", "start_period:"):
            assert field in doc, f"missing compose healthcheck field: {field}"
        assert "docker-compose.dev.yml" in doc
        assert "inherits" in doc.lower()

    def test_evaluation_doc_flags_missing_curl_risk(self):
        """Doc flags the concrete risk that the compose healthcheck's `curl` dependency is not
        installed anywhere in backend/Dockerfile's apt-get install list."""
        doc = _read_doc()
        assert "curl" in doc
        assert "fonts-liberation" in doc
        assert "python:3.11-slim" in doc

    def test_evaluation_doc_covers_three_options(self):
        """Doc compares at least three concrete options: (a) status quo, (b) a Dockerfile-level
        HEALTHCHECK instruction, (c) deepening GET /health to check a real dependency."""
        doc = _read_doc()
        assert "Status quo" in doc
        assert "HEALTHCHECK" in doc
        assert "Deepen" in doc or "deepen" in doc

    def test_evaluation_doc_ends_with_single_recommendation_gated_on_approval(self):
        """Doc ends with one clear recommendation and explicitly states no Dockerfile/backend
        change happens until the user reviews and approves it."""
        doc = _read_doc()
        assert "## Recommendation" in doc
        recommendation_section = doc.split("## Recommendation", 1)[1]
        assert "approv" in recommendation_section.lower()
        assert "No changes" in recommendation_section or "no changes" in recommendation_section.lower()


# ===========================================================================
# Story: Implement the Recommended Health Check — approved and implemented
# ===========================================================================

class TestHealthCheckImplementation:
    def test_health_check_returns_ok_when_db_reachable(self, db, monkeypatch):
        """GET /health reflects real service health via a lightweight DB connectivity
        check, not just process liveness."""
        monkeypatch.setenv("DEBUG", "true")  # only matters on main's first import; harmless no-op otherwise
        import main
        assert main.health(db=db) == {"status": "ok"}

    def test_health_check_returns_503_when_db_unreachable(self, monkeypatch):
        """A DB failure returns a non-2xx status rather than raising an unhandled exception,
        and does not become an expensive/slow check."""
        monkeypatch.setenv("DEBUG", "true")
        import main

        class _BrokenDb:
            def execute(self, *args, **kwargs):
                raise RuntimeError("db unreachable")

        response = main.health(db=_BrokenDb())
        assert response.status_code == 503

    def test_dockerfile_has_healthcheck_instruction(self):
        """A HEALTHCHECK instruction is added to backend/Dockerfile so the built image
        reports health under any orchestrator, not only via this repo's docker-compose.yml."""
        dockerfile = _read(_DOCKERFILE_PATH)
        assert "HEALTHCHECK" in dockerfile

    def test_healthcheck_command_does_not_depend_on_curl(self):
        """The healthcheck command does not depend on a binary absent from the image — it
        uses a dependency-free Python-based check instead of curl. (Explanatory comments may
        still mention "curl" by name; only the actual invoked command matters here.)"""
        dockerfile = _read(_DOCKERFILE_PATH)
        assert '"CMD", "curl"' not in dockerfile
        assert "CMD curl" not in dockerfile
        assert "python -c" in dockerfile
        assert "urllib.request" in dockerfile

    def test_compose_healthcheck_matches_dockerfile_no_curl(self):
        """docker-compose.yml's existing healthcheck block is updated to match the
        Dockerfile's, so there is no conflicting or silently broken duplicate definition."""
        compose = _read(_COMPOSE_PATH)
        assert '"CMD", "curl"' not in compose
        assert "urllib.request" in compose
        assert "urllib.request" in compose

    def test_commands_doc_explains_how_to_check_health_status(self):
        """markdown/features/reference/commands.md documents how an operator checks
        container health status."""
        commands_doc = _read(_COMMANDS_DOC_PATH)
        assert "docker compose ps" in commands_doc
        assert "State.Health" in commands_doc
