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
from sqlalchemy.pool import StaticPool

# ---------------------------------------------------------------------------
# Shared client fixture
# ---------------------------------------------------------------------------

@pytest.fixture
def client(monkeypatch):
    """Return a TestClient backed by an in-memory SQLite database.

    We reload the main module so middleware changes picked up from env vars.
    The DB lifecycle (create_all, migrations, seed) runs against :memory: so
    the test never touches the (possibly absent or read-only) local data/fantasy.db.
    """
    monkeypatch.setenv("AUTO_INGEST_LEAGUES", "")
    monkeypatch.setenv("DEBUG", "true")

    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    import importlib
    import database
    import main as main_module

    # Point the database module at an in-memory engine before reloading main.
    test_engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    test_session_factory = sessionmaker(bind=test_engine)
    monkeypatch.setattr(database, "engine", test_engine)
    monkeypatch.setattr(database, "SessionLocal", test_session_factory)

    # Patch every module that imported SessionLocal at its own module level so
    # background threads (enrich, ingest, seed) also use the in-memory engine.
    import enrich
    import ingest
    import seed
    monkeypatch.setattr(enrich, "SessionLocal", test_session_factory)
    monkeypatch.setattr(ingest, "SessionLocal", test_session_factory)
    monkeypatch.setattr(seed, "SessionLocal", test_session_factory)

    importlib.reload(main_module)

    # After reload, main has re-imported engine/SessionLocal from database —
    # set them again in main's namespace so lifespan uses the in-memory engine.
    main_module.engine = test_engine
    main_module.SessionLocal = test_session_factory

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
    # Parse the frame-ancestors directive into an exact token set, then use
    # set equality (not `in`) so CodeQL does not mistake this for URL
    # sanitization (py/incomplete-url-substring-sanitization).
    directives = {
        parts[0]: set(parts[1:])
        for d in csp.split(";")
        if (parts := d.strip().split())
    }
    fa_sources = directives.get("frame-ancestors", set())
    expected = {"'self'", "https://www.twitch.tv", "https://*.ext-twitch.tv"}
    assert expected == fa_sources, (
        f"frame-ancestors sources mismatch: expected {expected}, got {fa_sources}"
    )


def test_hsts_present_when_https_only_true(monkeypatch):
    """When HTTPS_ONLY=true, every response includes
    Strict-Transport-Security: max-age=31536000; includeSubDomains."""
    monkeypatch.setenv("AUTO_INGEST_LEAGUES", "")
    monkeypatch.setenv("DEBUG", "true")
    monkeypatch.setenv("HTTPS_ONLY", "true")

    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    import importlib
    import database
    import main as main_module

    test_engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    test_session_factory = sessionmaker(bind=test_engine)
    monkeypatch.setattr(database, "engine", test_engine)
    monkeypatch.setattr(database, "SessionLocal", test_session_factory)

    import enrich
    import ingest
    import seed
    monkeypatch.setattr(enrich, "SessionLocal", test_session_factory)
    monkeypatch.setattr(ingest, "SessionLocal", test_session_factory)
    monkeypatch.setattr(seed, "SessionLocal", test_session_factory)

    importlib.reload(main_module)
    main_module.engine = test_engine
    main_module.SessionLocal = test_session_factory

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
