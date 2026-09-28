"""
Tests for plan-issue-136-security-audit-3.md (resolves GitHub issue #136).

A third external review rated the security posture better than average and
listed four hardening areas plus a dependency audit. The plan groups them into
four user stories. One test per acceptance criterion (happy path plus the
primary failure path for each).

Testing approach per story:

  Story 1 — Reject Cross-Origin State Changes
    - HTTP-level tests via TestClient against `main.app`. Copy the `client`
      fixture from test_security_headers.py: set DEBUG=true and
      AUTO_INGEST_LEAGUES="", patch `database.engine`/`SessionLocal` (and
      enrich/ingest/seed SessionLocal) to an in-memory StaticPool engine, then
      `importlib.reload(main)`.
    - The middleware is env-dependent (`CSRF_ORIGIN_CHECK`, `APP_BASE_URL`).
      Either reload `main` after monkeypatching the env, or have the
      middleware read the settings per request; whichever the implementation
      picks, the tests must set env BEFORE the app is built/used.
    - Per lessons-learned (2026-09-24): opening `TestClient(main.app)` as a
      context manager runs the lifespan and starts `_backup_loop`. Also
      `monkeypatch.setattr(database, "DATABASE_URL", f"sqlite:///{tmp_path/'fantasy.db'}")`
      or use TestClient without `with` so the lifespan background loops never
      touch the real data/fantasy.db.
    - Per lessons-learned (2026-09-27): if rate limits interfere, reload only
      modules already in `sys.modules` (see `_build_app` in
      test_issue_135_security_review_fixes.py) — never reload a router twice.
    - Use a body-less state-changing route (e.g. POST /logout) and set the
      `Host` header explicitly (TestClient default host is "testserver").
      The assertion for "allowed" is "status != 403", since auth/validation
      may legitimately return 401/422.

  Story 2 — Username Allowlist for New Names
    - Unit tests on `RegisterBody` (routers/auth.py) and `UpdateUsernameBody`
      (routers/profile.py): construct with valid/invalid names, expect
      `pydantic.ValidationError` for invalid ones. `check_username()` in
      backend/auth.py can be tested directly too.
    - One HTTP test: POST /register with "bad name" returns 422 and the
      message lists the allowed characters.
    - Login with a legacy name: seed a `User` directly in the `db` fixture
      with a name like "näme" (bypassing the validator) and POST /login.
    - Frontend hint: static check of frontend/index.html (no JS runtime).

  Story 3 — CORS Limited to the Twitch Extension
    - Preflight OPTIONS requests via TestClient with `Origin` and
      `Access-Control-Request-Method: POST`. CORS config is read at import,
      so `CORS_EXTRA_ORIGINS` requires setting the env and reloading `main`.
    - `allow_credentials` checked by asserting no
      `Access-Control-Allow-Credentials: true` header on an allowed preflight.

  Story 4 — Production Guardrails for Secrets and Dependencies
    - Startup guards: run `import main` in a subprocess (precedent:
      test_issue_81_season_lifecycle.py::test_app_imports_cleanly_*) with a
      controlled env so module-level state is isolated. If the guard lives in
      the lifespan instead of module scope, the subprocess script must also
      enter `TestClient(main.app)` so startup runs; point DATABASE_URL at a
      tmp_path SQLite file.
    - CI and docs: static checks of .github/workflows/unit-tests.yml and
      .env.example.

Manual verification (not automated):
  - On staging, behind the real reverse proxy: log in, draw a card and change
    the roster — none should return 403. If they do, the proxy rewrites
    `Host`; set APP_BASE_URL or CSRF_ORIGIN_CHECK=false and report it.
  - The Twitch panel on Hosted Test still loads status and links an account
    (confirms the CORS regex matches the real extension origin).
  - The main site keeps working in a real browser (same-origin, no CORS).
  - The CI run on GitHub shows the pip-audit step passing, and it fails when
    a known-vulnerable pin is introduced.
  - Hoster deploy notes mention ENV=production (prose; reviewed by hand, but
    a light static check is included below).
"""
import os
import pathlib
import subprocess
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from starlette.middleware.sessions import SessionMiddleware

_BACKEND_DIR = pathlib.Path(__file__).resolve().parent.parent
_REPO_ROOT = _BACKEND_DIR.parent
_REFUSED = "Cross-origin request refused"
_LONG_SECRET = "x" * 40


def _read(rel_path):
    return (_REPO_ROOT / rel_path).read_text(encoding="utf-8")


def _build_main_client(monkeypatch, env=None):
    """Reload main against an in-memory DB and return a TestClient.

    Not entered as a context manager, so the lifespan (and its background
    loops, including _backup_loop) never runs; tables are created directly.
    CORS config is read at import time, so env must be set before this call.
    The Origin check reads CSRF_ORIGIN_CHECK / APP_BASE_URL per request.
    """
    import importlib
    import database
    import enrich
    import ingest
    import seed

    monkeypatch.setenv("AUTO_INGEST_LEAGUES", "")
    monkeypatch.setenv("DEBUG", "true")
    monkeypatch.delenv("ENV", raising=False)
    monkeypatch.delenv("CSRF_ORIGIN_CHECK", raising=False)
    monkeypatch.delenv("APP_BASE_URL", raising=False)
    monkeypatch.delenv("CORS_EXTRA_ORIGINS", raising=False)
    for key, value in (env or {}).items():
        monkeypatch.setenv(key, value)

    test_engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    factory = sessionmaker(bind=test_engine)
    database.Base.metadata.create_all(test_engine)
    monkeypatch.setattr(database, "engine", test_engine)
    monkeypatch.setattr(database, "SessionLocal", factory)
    monkeypatch.setattr(enrich, "SessionLocal", factory)
    monkeypatch.setattr(ingest, "SessionLocal", factory)
    monkeypatch.setattr(seed, "SessionLocal", factory)

    import main
    importlib.reload(main)
    main.engine = test_engine
    main.SessionLocal = factory
    return TestClient(main.app, raise_server_exceptions=False)


@pytest.fixture
def main_client(monkeypatch):
    return _build_main_client(monkeypatch)


def _is_refused(resp):
    if resp.status_code != 403:
        return False
    try:
        return resp.json().get("detail") == _REFUSED
    except ValueError:
        return False


@pytest.fixture
def auth_env():
    """Minimal app with the auth + profile routers on a StaticPool in-memory DB."""
    import rate_limit
    from database import Base, get_db
    from routers import auth as auth_router
    from routers import profile as profile_router

    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)

    def _override_get_db():
        s = Session()
        try:
            yield s
        finally:
            s.close()

    was_enabled = rate_limit.limiter.enabled
    rate_limit.limiter.enabled = False
    app = FastAPI()
    app.add_middleware(SessionMiddleware, secret_key="test-secret-key-123")
    app.include_router(auth_router.router)
    app.include_router(profile_router.router)
    app.dependency_overrides[get_db] = _override_get_db
    try:
        yield TestClient(app), Session
    finally:
        rate_limit.limiter.enabled = was_enabled


def _run_import_main(tmp_path, env_overrides):
    """Run `import main` in a subprocess with a controlled environment."""
    env = {
        k: v for k, v in os.environ.items()
        if k not in ("ENV", "DEBUG", "TWITCH_LOCAL_DEV", "SECRET_KEY", "AUTO_INGEST_LEAGUES")
    }
    env["DATABASE_URL"] = f"sqlite:///{tmp_path / 'fantasy.db'}"
    # Isolate the ENV/SECRET_KEY guards from the issue #118 HTTPS_ONLY startup check.
    env["HTTPS_ONLY"] = "true"
    env.update(env_overrides)
    return subprocess.run(
        [sys.executable, "-c", "import main"],
        cwd=str(_BACKEND_DIR), env=env, capture_output=True, text=True, timeout=120,
    )


# ---------------------------------------------------------------------------
# Story 1 — Reject Cross-Origin State Changes
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE"])
def test_origin_check_foreign_origin_unsafe_method_returns_403(main_client, method):
    """Unsafe method outside /twitch/ with a foreign Origin host returns 403 'Cross-origin request refused'."""
    resp = main_client.request(
        method, "/logout",
        headers={"Host": "kana-cards.com", "Origin": "https://evil.example"},
    )
    assert resp.status_code == 403
    assert resp.json() == {"detail": _REFUSED}


def test_origin_check_same_host_origin_allowed(main_client):
    """Origin whose host equals the request Host header is not refused (status != 403)."""
    resp = main_client.post(
        "/logout",
        headers={"Host": "kana-cards.com", "Origin": "https://KANA-CARDS.com"},
    )
    assert resp.status_code != 403
    resp = main_client.post(
        "/logout",
        headers={"Host": "localhost:8000", "Origin": "http://localhost:8000"},
    )
    assert resp.status_code != 403
    # Same hostname but a different port is a different origin.
    resp = main_client.post(
        "/logout",
        headers={"Host": "localhost:8000", "Origin": "http://localhost:9999"},
    )
    assert _is_refused(resp)


def test_origin_check_app_base_url_host_allowed(main_client, monkeypatch):
    """Origin whose host equals the host of APP_BASE_URL is allowed even when Host differs."""
    headers = {"Host": "internal-app:8000", "Origin": "https://kana-cards.com"}
    assert _is_refused(main_client.post("/logout", headers=headers))
    monkeypatch.setenv("APP_BASE_URL", "https://kana-cards.com/")
    resp = main_client.post("/logout", headers=headers)
    assert resp.status_code != 403


def test_origin_check_referer_fallback_foreign_returns_403(main_client):
    """With no Origin, a Referer from a foreign host causes 403."""
    resp = main_client.post(
        "/logout",
        headers={"Host": "kana-cards.com", "Referer": "https://evil.example/page"},
    )
    assert _is_refused(resp)


def test_origin_check_referer_fallback_same_host_allowed(main_client):
    """With no Origin, a same-host Referer is allowed."""
    resp = main_client.post(
        "/logout",
        headers={"Host": "kana-cards.com", "Referer": "https://kana-cards.com/#roster"},
    )
    assert resp.status_code != 403


def test_origin_check_no_origin_no_referer_allowed(main_client):
    """When both Origin and Referer are absent (API clients, tests), the request is allowed."""
    resp = main_client.post("/logout", headers={"Host": "kana-cards.com"})
    assert resp.status_code != 403


def test_origin_check_unparseable_origin_refused(main_client):
    """An unparseable or opaque Origin (e.g. 'null') is treated as foreign."""
    for bad in ("null", "not a url", "https://[::1"):
        resp = main_client.post("/logout", headers={"Host": "kana-cards.com", "Origin": bad})
        assert _is_refused(resp), bad


@pytest.mark.parametrize("method", ["GET", "HEAD", "OPTIONS"])
def test_origin_check_safe_methods_never_blocked(main_client, method):
    """GET, HEAD and OPTIONS with a foreign Origin are never refused with 403 by the Origin check."""
    resp = main_client.request(
        method, "/health",
        headers={"Host": "kana-cards.com", "Origin": "https://evil.example"},
    )
    assert not _is_refused(resp)
    assert resp.status_code != 403


def test_origin_check_twitch_paths_exempt(main_client):
    """POST to a /twitch/* route with a foreign (ext-twitch.tv) Origin is not refused by the Origin check."""
    resp = main_client.post(
        "/twitch/heartbeat",
        headers={"Host": "kana-cards.com", "Origin": "https://abc123.ext-twitch.tv"},
    )
    assert not _is_refused(resp)
    assert resp.status_code != 403


def test_origin_check_applies_to_cookie_auth_twitch_link_code(main_client):
    """POST /twitch/link-code uses the session cookie, so a sibling-subdomain Origin is refused."""
    resp = main_client.post(
        "/twitch/link-code",
        headers={"Host": "kana-cards.com", "Origin": "https://test.kana-cards.com"},
    )
    assert _is_refused(resp)


def test_origin_check_allows_same_origin_twitch_link_code(main_client):
    """A same-origin POST /twitch/link-code is not refused by the Origin check (auth decides next)."""
    resp = main_client.post(
        "/twitch/link-code",
        headers={"Host": "kana-cards.com", "Origin": "https://kana-cards.com"},
    )
    assert not _is_refused(resp)


def test_origin_check_disabled_by_env_flag(main_client, monkeypatch):
    """CSRF_ORIGIN_CHECK=false disables the check: a foreign Origin POST is no longer 403."""
    monkeypatch.setenv("CSRF_ORIGIN_CHECK", "false")
    resp = main_client.post(
        "/logout",
        headers={"Host": "kana-cards.com", "Origin": "https://evil.example"},
    )
    assert resp.status_code != 403


def test_origin_check_enabled_by_default(main_client, monkeypatch):
    """With CSRF_ORIGIN_CHECK unset, the check is on and a foreign Origin POST returns 403."""
    monkeypatch.delenv("CSRF_ORIGIN_CHECK", raising=False)
    resp = main_client.post(
        "/logout",
        headers={"Host": "kana-cards.com", "Origin": "https://evil.example"},
    )
    assert _is_refused(resp)


def test_origin_check_sibling_subdomain_refused(main_client):
    """Origin https://test.kana-cards.com POST /draw with Host kana-cards.com returns 403."""
    resp = main_client.post(
        "/draw",
        headers={"Host": "kana-cards.com", "Origin": "https://test.kana-cards.com"},
    )
    assert _is_refused(resp)


# ---------------------------------------------------------------------------
# Story 2 — Username Allowlist for New Names
# ---------------------------------------------------------------------------

def test_register_body_accepts_allowlisted_username():
    """RegisterBody accepts names matching ^[A-Za-z0-9_-]+$ within 1–64 characters."""
    from routers.auth import RegisterBody
    for name in ("a", "Alice_99", "carol-renamed", "_-_", "Z" * 64):
        body = RegisterBody(username=name, email="a@example.com", password="secret123")
        assert body.username == name


@pytest.mark.parametrize("name", ["bad name", "näme", "a<b", "zero\u200bwidth", "x" * 65, ""])
def test_register_body_rejects_disallowed_username(name):
    """RegisterBody rejects names with spaces, non-ASCII, markup, invisible characters or bad length."""
    from routers.auth import RegisterBody
    with pytest.raises(ValidationError):
        RegisterBody(username=name, email="a@example.com", password="secret123")


def test_update_username_body_accepts_allowlisted_username():
    """UpdateUsernameBody (PUT /profile/username) accepts names matching the allowlist."""
    from routers.profile import UpdateUsernameBody
    for name in ("bob", "Bob_2", "b-o-b", "9" * 64):
        assert UpdateUsernameBody(username=name).username == name


def test_update_username_body_rejects_disallowed_username():
    """UpdateUsernameBody rejects names outside ^[A-Za-z0-9_-]+$."""
    from routers.profile import UpdateUsernameBody
    for name in ("bad name", "näme", "a.b", "o'brien", "tab\there", "x" * 65, ""):
        with pytest.raises(ValidationError):
            UpdateUsernameBody(username=name)


def test_check_username_helper():
    """auth.check_username returns valid names unchanged and raises ValueError otherwise."""
    from auth import check_username
    assert check_username("ok_name-1") == "ok_name-1"
    with pytest.raises(ValueError):
        check_username("näme")
    with pytest.raises(ValueError):
        check_username("trailing\n")


def test_register_endpoint_invalid_username_returns_422_with_allowed_chars_message(auth_env):
    """POST /register with 'bad name' returns 422 and the message lists the allowed characters."""
    client, _ = auth_env
    resp = client.post(
        "/register",
        json={"username": "bad name", "email": "bad@example.com", "password": "secret123"},
    )
    assert resp.status_code == 422
    msgs = " ".join(
        e.get("msg", "") for e in resp.json()["detail"] if "username" in e.get("loc", [])
    )
    for fragment in ("letters", "digits", "underscore", "hyphen"):
        assert fragment in msgs, msgs


def test_login_legacy_username_outside_pattern_still_works(auth_env):
    """An existing account whose name violates the pattern (seeded directly) can still POST /login."""
    from auth import hash_password
    from models import User
    client, Session = auth_env
    s = Session()
    try:
        s.add(User(username="näme legacy", password_hash=hash_password("secret123")))
        s.commit()
    finally:
        s.close()
    resp = client.post("/login", json={"username": "näme legacy", "password": "secret123"})
    assert resp.status_code == 200, resp.text


def test_login_body_has_no_charset_check():
    """LoginBody accepts a name outside the allowlist (no charset validator), so legacy names are not rejected."""
    from routers.auth import LoginBody
    body = LoginBody(username="näme with space", password="whatever")
    assert body.username == "näme with space"


def test_frontend_register_and_username_forms_show_allowed_chars_hint():
    """frontend/index.html shows the allowed-character hint on the register and username-change forms."""
    import re
    html = _read("frontend/index.html")
    hints = re.findall(r'id="(regUsernameHint|profileUsernameHint)"[^>]*>([^<]*)<', html)
    ids = {h[0] for h in hints}
    assert ids == {"regUsernameHint", "profileUsernameHint"}, hints
    assert 'aria-describedby="regUsernameHint"' in html
    assert 'aria-describedby="profileUsernameHint"' in html
    for _, text in hints:
        low = text.lower()
        assert "letters" in low and "digits" in low and "_" in text and "-" in text, text


# ---------------------------------------------------------------------------
# Story 3 — CORS Limited to the Twitch Extension
# ---------------------------------------------------------------------------

def _preflight(client, origin):
    return client.options(
        "/twitch/status",
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "Authorization, Content-Type",
        },
    )


def test_cors_preflight_from_ext_twitch_origin_allowed(main_client):
    """Preflight from https://abc123.ext-twitch.tv gets Access-Control-Allow-Origin echoing that origin."""
    resp = _preflight(main_client, "https://abc123.ext-twitch.tv")
    assert resp.status_code == 200
    assert resp.headers.get("access-control-allow-origin") == "https://abc123.ext-twitch.tv"


def test_cors_preflight_from_foreign_origin_has_no_acao_header(main_client):
    """Preflight from https://example.com gets no Access-Control-Allow-Origin header."""
    resp = _preflight(main_client, "https://example.com")
    assert "access-control-allow-origin" not in resp.headers


def test_cors_regex_rejects_lookalike_ext_twitch_origins(main_client):
    """http:// scheme or evil.ext-twitch.tv.attacker.com origins do not get an ACAO header."""
    for origin in (
        "http://abc123.ext-twitch.tv",
        "https://evil.ext-twitch.tv.attacker.com",
        "https://a.b.ext-twitch.tv",
        "https://ext-twitch.tv",
    ):
        resp = _preflight(main_client, origin)
        assert "access-control-allow-origin" not in resp.headers, origin


def test_cors_extra_origins_env_adds_origin(monkeypatch):
    """CORS_EXTRA_ORIGINS=http://localhost:8080 (reloaded main) makes that origin's preflight succeed."""
    client = _build_main_client(
        monkeypatch, {"CORS_EXTRA_ORIGINS": " http://localhost:8080 , https://other.test"}
    )
    for origin in ("http://localhost:8080", "https://other.test"):
        resp = _preflight(client, origin)
        assert resp.status_code == 200
        assert resp.headers.get("access-control-allow-origin") == origin
    # The regex still applies alongside the extra list.
    resp = _preflight(client, "https://abc123.ext-twitch.tv")
    assert resp.headers.get("access-control-allow-origin") == "https://abc123.ext-twitch.tv"
    # Without the env var the Local Test origin is not allowed.
    client = _build_main_client(monkeypatch)
    resp = _preflight(client, "http://localhost:8080")
    assert "access-control-allow-origin" not in resp.headers


def test_cors_allow_credentials_stays_false(main_client):
    """An allowed preflight carries no Access-Control-Allow-Credentials: true header."""
    resp = _preflight(main_client, "https://abc123.ext-twitch.tv")
    assert resp.headers.get("access-control-allow-origin") == "https://abc123.ext-twitch.tv"
    assert resp.headers.get("access-control-allow-credentials") != "true"


def test_cors_no_wildcard_allow_origins_in_main_source():
    """main.py no longer configures allow_origins=["*"]."""
    import re
    source = (_BACKEND_DIR / "main.py").read_text()
    assert not re.search(r"allow_origins\s*=\s*\[\s*[\"']\*[\"']\s*\]", source)
    assert "allow_credentials=False" in source


def test_env_example_documents_cors_extra_origins():
    """.env.example documents CORS_EXTRA_ORIGINS with http://localhost:8080 as the Local Test example."""
    content = _read(".env.example")
    assert "CORS_EXTRA_ORIGINS" in content
    lines = [l for l in content.splitlines() if "CORS_EXTRA_ORIGINS" in l]
    assert any("http://localhost:8080" in l for l in lines), lines


def test_env_example_documents_csrf_origin_check():
    """.env.example documents CSRF_ORIGIN_CHECK."""
    content = _read(".env.example")
    assert "CSRF_ORIGIN_CHECK" in content


# ---------------------------------------------------------------------------
# Story 4 — Production Guardrails for Secrets and Dependencies
# ---------------------------------------------------------------------------

def test_production_startup_ok_with_long_secret_and_no_dev_flags(tmp_path):
    """ENV=production with a 32+ char SECRET_KEY and no dev flags imports/starts main cleanly (subprocess)."""
    result = _run_import_main(tmp_path, {"ENV": "production", "SECRET_KEY": _LONG_SECRET})
    assert result.returncode == 0, result.stderr


def test_production_startup_fails_with_debug_true(tmp_path):
    """ENV=production + DEBUG=true fails startup with a clear RuntimeError even when SECRET_KEY is set."""
    result = _run_import_main(
        tmp_path, {"ENV": "production", "SECRET_KEY": _LONG_SECRET, "DEBUG": "true"}
    )
    assert result.returncode != 0
    assert "RuntimeError" in result.stderr
    assert "DEBUG=true" in result.stderr and "ENV=production" in result.stderr


def test_production_startup_fails_with_twitch_local_dev_true(tmp_path):
    """ENV=production + TWITCH_LOCAL_DEV=true fails startup with a clear RuntimeError."""
    result = _run_import_main(
        tmp_path, {"ENV": "Production", "SECRET_KEY": _LONG_SECRET, "TWITCH_LOCAL_DEV": "true"}
    )
    assert result.returncode != 0
    assert "RuntimeError" in result.stderr
    assert "TWITCH_LOCAL_DEV=true" in result.stderr


def test_production_startup_fails_with_short_secret_key(tmp_path):
    """ENV=production with a SECRET_KEY shorter than 32 characters fails startup with a RuntimeError."""
    result = _run_import_main(tmp_path, {"ENV": "production", "SECRET_KEY": "x" * 31})
    assert result.returncode != 0
    assert "RuntimeError" in result.stderr
    assert "32" in result.stderr
    result = _run_import_main(tmp_path, {"ENV": "production", "SECRET_KEY": "x" * 32})
    assert result.returncode == 0, result.stderr


def test_non_production_short_secret_key_still_starts(tmp_path):
    """Without ENV=production a short SECRET_KEY is still accepted (guard is production-only)."""
    result = _run_import_main(tmp_path, {"SECRET_KEY": "short"})
    assert result.returncode == 0, result.stderr


def _workflow_steps():
    """Split unit-tests.yml into its step blocks (text-based; PyYAML is not a dependency)."""
    import re
    text = _read(".github/workflows/unit-tests.yml")
    steps_start = text.index("steps:")
    return [
        chunk for chunk in re.split(r"\n\s*- (?=uses:|name:|run:)", text[steps_start:])[1:]
    ]


def _pip_audit_index(steps):
    for i, step in enumerate(steps):
        if "pip-audit -r backend/requirements.txt" in step:
            return i
    return None


def test_unit_tests_workflow_runs_pip_audit_on_requirements():
    """.github/workflows/unit-tests.yml runs `pip-audit -r backend/requirements.txt` after dependency install."""
    steps = _workflow_steps()
    audit = _pip_audit_index(steps)
    assert audit is not None, "no pip-audit step"
    install = next(
        i for i, s in enumerate(steps)
        if "pip install -r backend/requirements" in s
    )
    assert install < audit


def test_unit_tests_workflow_pip_audit_not_continue_on_error():
    """The pip-audit step is not marked continue-on-error, so a known vulnerability fails the job."""
    steps = _workflow_steps()
    step = steps[_pip_audit_index(steps)]
    assert "continue-on-error" not in step
    assert "|| true" not in step


def test_env_example_documents_env_production():
    """.env.example documents ENV=production."""
    assert "ENV=production" in _read(".env.example")


def test_deploy_notes_mention_env_production():
    """The in-repo deployment guide (README.md Deployment section) tells operators to set ENV=production.

    The hoster's own deploy notes live outside the repo, so the README's
    Deployment section is the checked-in equivalent.
    """
    readme = _read("README.md")
    start = readme.index("## Deployment")
    nxt = readme.find("\n## ", start + 1)
    section = readme[start:nxt if nxt != -1 else None]
    assert "ENV=production" in section
