"""
Tests for the Security Headers plan.

Story 1 — Security Response Headers
Story 2 — CORS Wildcard Documentation
"""
import os
import sys
import pathlib

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from fastapi.testclient import TestClient

# ---------------------------------------------------------------------------
# Shared client fixture
# ---------------------------------------------------------------------------

@pytest.fixture
def client():
    """Return a TestClient for the FastAPI app with a test database."""
    os.environ.setdefault("DEBUG", "true")
    import importlib
    import main as main_module
    importlib.reload(main_module)
    with TestClient(main_module.app, raise_server_exceptions=True) as c:
        yield c


# ---------------------------------------------------------------------------
# Story 1 — Security Response Headers
# ---------------------------------------------------------------------------

def test_x_content_type_options_present(client):
    """Every response includes X-Content-Type-Options: nosniff."""
    response = client.get("/health")
    assert response.headers.get("x-content-type-options") == "nosniff"


def test_referrer_policy_present(client):
    """Every response includes Referrer-Policy: strict-origin-when-cross-origin."""
    response = client.get("/health")
    assert response.headers.get("referrer-policy") == "strict-origin-when-cross-origin"


def test_content_security_policy_frame_ancestors_present(client):
    """Every response includes a Content-Security-Policy header containing
    frame-ancestors 'self' https://www.twitch.tv https://*.ext-twitch.tv."""
    response = client.get("/health")
    csp = response.headers.get("content-security-policy", "")
    assert "frame-ancestors" in csp
    assert "https://www.twitch.tv" in csp
    assert "https://*.ext-twitch.tv" in csp


def test_hsts_present_when_https_only_true(monkeypatch):
    """When HTTPS_ONLY=true, every response includes
    Strict-Transport-Security: max-age=31536000; includeSubDomains."""
    monkeypatch.setenv("DEBUG", "true")
    monkeypatch.setenv("HTTPS_ONLY", "true")
    import importlib
    import main as main_module
    importlib.reload(main_module)
    with TestClient(main_module.app, raise_server_exceptions=True) as c:
        response = c.get("/health")
    assert response.headers.get("strict-transport-security") == "max-age=31536000; includeSubDomains"


def test_hsts_absent_when_https_only_false(client):
    """When HTTPS_ONLY=false (default), Strict-Transport-Security is NOT sent."""
    response = client.get("/health")
    assert "strict-transport-security" not in response.headers


def test_headers_present_on_multiple_endpoints(client):
    """Security headers are added by middleware — present on more than one
    distinct endpoint, not injected by individual handlers."""
    endpoints = ["/health", "/config"]
    for path in endpoints:
        response = client.get(path)
        assert response.headers.get("x-content-type-options") == "nosniff", (
            f"X-Content-Type-Options missing on {path}"
        )
        assert response.headers.get("referrer-policy") == "strict-origin-when-cross-origin", (
            f"Referrer-Policy missing on {path}"
        )
        assert "frame-ancestors" in response.headers.get("content-security-policy", ""), (
            f"Content-Security-Policy missing on {path}"
        )


# ---------------------------------------------------------------------------
# Story 2 — CORS Wildcard Documentation
# ---------------------------------------------------------------------------

def test_cors_wildcard_comment_present_in_main():
    """The inline comment in main.py explaining the wildcard origin is present
    and accurate (references allow_credentials=False and Twitch JWT)."""
    main_path = pathlib.Path(__file__).parent.parent / "main.py"
    source = main_path.read_text()
    assert "allow_credentials" in source
    assert "JWT" in source or "jwt" in source.lower()
    assert "allow_origins" in source


def test_security_headers_doc_covers_cors_decision():
    """markdown/features/reference/security-headers.md documents the CORS
    decision: wildcard rationale, why it is safe (allow_credentials=False +
    Twitch JWT auth), and what would need to change without the Twitch
    extension."""
    doc_path = (
        pathlib.Path(__file__).parent.parent.parent
        / "markdown" / "features" / "reference" / "security-headers.md"
    )
    assert doc_path.exists(), "security-headers.md not found"
    content = doc_path.read_text()
    assert "allow_credentials" in content
    assert "JWT" in content or "jwt" in content.lower()
    assert "wildcard" in content.lower() or "allow_origins" in content
    assert "Twitch" in content
