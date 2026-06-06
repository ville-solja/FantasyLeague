# Plan: Security Headers

## Context
A Nikto v2.6.0 scan of the production host flagged several missing HTTP security response
headers: `Strict-Transport-Security`, `Referrer-Policy`, `Content-Security-Policy` (with
`frame-ancestors` to replace the deprecated `X-Frame-Options`), and `X-Content-Type-Options`.
The scan also flagged `access-control-allow-origin: *` — this is intentional for the Twitch
extension (iframes are served from a different origin) and is safe because
`allow_credentials=False` prevents cross-origin session cookie abuse; the plan documents
this decision rather than removing the wildcard. A single Starlette middleware class added
to `backend/main.py` injects the missing headers on every response. *Resolves GitHub
issue #69.*

## User Stories

### Security Response Headers
**User story**
As an operator, I want the server to return standard security response headers so that
vulnerability scanners report no missing-header findings and browsers apply protective
policies.

**Acceptance criteria**
- Every response includes `X-Content-Type-Options: nosniff`
- Every response includes `Referrer-Policy: strict-origin-when-cross-origin`
- Every response includes a `Content-Security-Policy` header containing at least
  `frame-ancestors 'self' https://www.twitch.tv https://*.ext-twitch.tv`
- When `HTTPS_ONLY=true`, every response includes
  `Strict-Transport-Security: max-age=31536000; includeSubDomains`
- When `HTTPS_ONLY=false` (default), `Strict-Transport-Security` is not sent
- The headers are added by a middleware layer and do not require changes to individual
  endpoint handlers

### CORS Wildcard Documentation
**User story**
As a security reviewer, I want the intentional `access-control-allow-origin: *`
configuration to be explained in the codebase and documentation so that it is not
misread as an oversight.

**Acceptance criteria**
- The existing inline comment in `main.py` explaining the wildcard is preserved and
  accurate
- `markdown/features/reference/security-headers.md` documents the CORS decision: why
  wildcard is used, why it is safe (`allow_credentials=False` + Twitch JWT auth), and what
  would need to change if the Twitch extension were removed

---

## Implementation

### Critical Files
| File | Change |
|---|---|
| `backend/main.py` | Add `SecurityHeadersMiddleware` class; register it after `SessionMiddleware` |
| `markdown/features/reference/security-headers.md` | New operator guide (created by product-planner) |

No model changes, no migrations, no `.env.example` changes (HTTPS_ONLY already documented).

### Step 1 — Add `SecurityHeadersMiddleware` to `backend/main.py`

Add the class immediately before the `app.add_middleware` calls:

```python
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Content-Security-Policy"] = (
            "frame-ancestors 'self' https://www.twitch.tv https://*.ext-twitch.tv"
        )
        if _https_only:
            response.headers["Strict-Transport-Security"] = (
                "max-age=31536000; includeSubDomains"
            )
        return response
```

Register it after the `SessionMiddleware` block and before `CORSMiddleware`:

```python
app.add_middleware(SecurityHeadersMiddleware)
```

Note: `_https_only` is already resolved earlier in the file from `os.getenv("HTTPS_ONLY", "false")`.

### Step 2 — Write tests

Add `backend/tests/test_security_headers.py` using the existing FastAPI `TestClient`
pattern from `conftest.py`. For each header:
- Call any public endpoint (e.g. `GET /health` or `GET /config`)
- Assert the expected header is present in the response
- Assert HSTS is absent when `HTTPS_ONLY` is not set; present when it is

### Step 3 — Fill in the feature doc stub

Update `markdown/features/reference/security-headers.md` with the completed description
including the header table and CORS rationale.

---

## Verification
- Start the app locally; `curl -I http://localhost:8000/config` and verify all four headers
  appear in the response
- Set `HTTPS_ONLY=true`; repeat the curl and verify `Strict-Transport-Security` is present
- Leave `HTTPS_ONLY` unset; verify `Strict-Transport-Security` is absent
- Check that the Twitch extension iframe still loads (no `frame-ancestors` rejection in
  browser console)
- Run `cd backend && python -m pytest tests/test_security_headers.py -v`
