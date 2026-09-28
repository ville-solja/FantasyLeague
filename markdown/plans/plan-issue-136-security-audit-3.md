# Plan: Security Audit 3 Hardening

## Context
A third external review, attached to issue #136, rates the app's security posture as better than average. It lists four areas to improve plus a dependency audit. On 2026-09-28 each point was checked against the current code:

| # | Finding | Verified state | Our severity | Decision |
|---|---|---|---|---|
| 1 | No CSRF tokens on cookie-authenticated routes | Largely mitigated. The session cookie is `SameSite=Lax`, so browsers don't send it on cross-site POSTs. FastAPI 0.138 rejects JSON bodies sent as `text/plain` or form-encoded (tested: 422), so a cross-site HTML form can't reach JSON endpoints. CORS never allows credentials. The gap left is **same-site** pages, such as `test.kana-cards.com` or any other `*.kana-cards.com` host. Their requests carry the cookie, including to body-less POSTs like `/draw`, `/logout` and `/roster/{id}/activate`. | Low | Fix: Origin check on unsafe methods (Story 1) |
| 2 | Username validation is a blocklist (`< > " '`) | Accurate. Output is now escaped everywhere (issue #135), so this is defence in depth. All 24 usernames in the local database copy already match `^[A-Za-z0-9_-]+$`. | Low | Fix for new registrations and renames; existing names keep working (Story 2) |
| 3 | CORS `allow_origins=["*"]` | Safe as the review says, because `allow_credentials=False`. Only the Twitch extension iframe (`https://<client-id>.ext-twitch.tv`) makes cross-origin calls. | Info | Fix: restrict to the extension origin, with an env var for Local Test (Story 3) |
| 4 | `SECRET_KEY` falls back to a dev value | Already enforced. `main.py` refuses to start without `SECRET_KEY` unless `DEBUG=true` or `TWITCH_LOCAL_DEV=true`. The remaining risk is one of those dev flags being set in production. | Low | Fix: refuse dev bypasses when `ENV=production` (Story 4) |
| 5 | Run `pip audit` on requirements | Dependabot is enabled: 19 alerts, all fixed, none open. Nothing checks for new CVEs at pull-request time. | Info | Fix: add `pip-audit` to CI (Story 4) |

**Assumptions:**
- The reverse proxy passes the original `Host` header, which Caddy and Traefik do by default. The Origin check compares against it and against `APP_BASE_URL`. It can be switched off with an env var if a deployment rewrites `Host`.
- `/twitch/*` routes are exempt from the Origin check. They authenticate with a Twitch JWT in the `Authorization` header, not the session cookie, and are called from the extension's origin.

Resolves GitHub issue #136.

## User Stories

### Reject Cross-Origin State Changes
**User story**
As a logged-in player, I want the server to refuse state-changing requests that come from another site, including sibling subdomains, so that a malicious page cannot act with my session.

**Acceptance criteria**
- For `POST`, `PUT`, `PATCH` and `DELETE` requests outside `/twitch/` (plus `POST /twitch/link-code`, which uses the session cookie), the server returns 403 when the `Origin` header is present and its host matches neither the request's `Host` nor the host of `APP_BASE_URL`
- When `Origin` is absent, the same check applies to the `Referer` header. When both are absent the request is allowed, as for API clients and tests
- `GET`, `HEAD` and `OPTIONS` requests are never blocked
- `CSRF_ORIGIN_CHECK=false` disables the check; it is on by default
- A request from `https://test.kana-cards.com` to `https://kana-cards.com/draw` is refused with 403

### Username Allowlist for New Names
**User story**
As an admin, I want new usernames limited to plain letters, digits, underscores and hyphens, so that names cannot carry markup, look-alike characters or invisible characters.

**Acceptance criteria**
- `POST /register` and `PUT /profile/username` accept only usernames matching `^[A-Za-z0-9_-]+$`, still 1–64 characters, and return 422 otherwise with a message listing the allowed characters
- Existing accounts whose names fall outside the pattern can still log in, and keep their name until they choose to change it
- The registration and profile forms show the allowed characters before submission

### CORS Limited to the Twitch Extension
**User story**
As the operator, I want cross-origin API access limited to the Twitch extension so that scanners stop flagging a wildcard CORS policy, while the extension keeps working.

**Acceptance criteria**
- CORS allows origins matching `^https://[a-z0-9]+\.ext-twitch\.tv$`, plus any comma-separated origins in `CORS_EXTRA_ORIGINS`
- `allow_credentials` stays `False`
- A preflight from `https://abc123.ext-twitch.tv` succeeds, and one from `https://example.com` gets no `Access-Control-Allow-Origin` header
- The main site keeps working, because it is same-origin and needs no CORS
- `.env.example` documents `CORS_EXTRA_ORIGINS`, with `http://localhost:8080` as the example for Twitch Local Test

### Production Guardrails for Secrets and Dependencies
**User story**
As the operator, I want production to refuse insecure dev shortcuts and CI to flag vulnerable dependencies, so that a stray flag or a new CVE is caught before it reaches users.

**Acceptance criteria**
- With `ENV=production`, startup fails with a clear error when `DEBUG=true` or `TWITCH_LOCAL_DEV=true`, even if `SECRET_KEY` is set
- With `ENV=production`, startup fails when `SECRET_KEY` is shorter than 32 characters
- The unit-test GitHub workflow runs `pip-audit -r backend/requirements.txt` and fails on a known vulnerability
- The hoster deploy notes say to set `ENV=production`

## Implementation

### Critical Files
| File | Change |
|---|---|
| `backend/main.py` | Origin-check middleware; CORS regex and extra origins; production guards on dev bypasses and secret length |
| `backend/routers/auth.py`, `backend/routers/profile.py` | Username allowlist validator, shared through `backend/auth.py` |
| `frontend/index.html` | Allowed-character hints on the register and username-change forms |
| `.github/workflows/unit-tests.yml` | `pip-audit` step |
| `.env.example` | `CSRF_ORIGIN_CHECK`, `CORS_EXTRA_ORIGINS`, `ENV=production` guidance |
| `backend/tests/test_issue_136_security_audit_3.py` | Tests for every acceptance criterion |
| `markdown/features/reference/security-headers.md` | Origin check and the CORS change |

No model change and no migration.

### Step 1 — Origin check middleware
Add a small Starlette middleware in `main.py`, registered with the existing security headers middleware. For unsafe methods on paths not starting with `/twitch/`, read `Origin`, falling back to `Referer`. Parse the host with `urllib.parse.urlsplit`. Allow the request if the host equals the request's `Host` header or the host of `APP_BASE_URL`, otherwise return `JSONResponse({"detail": "Cross-origin request refused"}, status_code=403)`. Skip the check entirely when `CSRF_ORIGIN_CHECK=false`.

### Step 2 — Username allowlist
Add `check_username()` to `backend/auth.py` next to `check_email()`, using `^[A-Za-z0-9_-]+$`. Replace the blocklist validators in `RegisterBody` and `UpdateUsernameBody`. `LoginBody` gets no charset check, so existing names still log in.

### Step 3 — CORS
Replace `allow_origins=["*"]` with `allow_origin_regex=r"^https://[a-z0-9]+\.ext-twitch\.tv$"` and `allow_origins=` the parsed `CORS_EXTRA_ORIGINS` list. Keep the methods, headers and `allow_credentials=False`.

### Step 4 — Production guards and CI
- In `main.py`: `if os.getenv("ENV", "").lower() == "production"`, raise `RuntimeError` when a dev bypass is active or `SECRET_KEY` has fewer than 32 characters.
- Add a `pip-audit` step to `.github/workflows/unit-tests.yml` after dependency install.

### Step 5 — Docs
- Update `security-headers.md` with the Origin check and CORS change.
- Update `core/auth.md` with the username rule.
- Update `twitch-extension.md` with the CORS origins and the Local Test note.
- Add `ENV=production` and a staging check of the Origin rule to the hoster deploy notes.

## Verification
- `cd backend && python3 -m pytest tests/test_issue_136_security_audit_3.py -v`, then the full suite. Bump the suite-size tripwire in `test_issue_85_split_admin_router.py`.
- Existing tests that post without an `Origin` header keep passing. Browser-like requests from the same origin pass, and requests from a foreign `Origin` get 403.
- **On staging, behind the real proxy:** log in, draw a card and change the roster. None should return 403. If they do, the proxy rewrites `Host`: set `APP_BASE_URL` or `CSRF_ORIGIN_CHECK=false` and report it.
- The Twitch panel on Hosted Test still loads status and links an account, which confirms the CORS change works.
- Registering `bad name` or `näme` returns 422. An existing user with such a name, if any, can still log in.
- Starting with `ENV=production DEBUG=true` fails with a clear message.
- The CI run shows the `pip-audit` step passing.
