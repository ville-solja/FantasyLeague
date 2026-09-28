# HTTPS Enforcement

Fails loudly at startup if `HTTPS_ONLY` isn't set (outside local dev), and makes the
TLS/reverse-proxy requirement for production explicit in the README, closing a gap where
session cookies — including an admin's — could be intercepted on unencrypted connections.

*(see `markdown/plans/plan-issue-118-https-enforcement.md`, resolves GitHub issue #118)*

---

## The vulnerability

`SessionMiddleware` (`backend/main.py`) only sets the session cookie's `Secure` flag when
`HTTPS_ONLY=true` is explicitly set. Nothing in the app enforced this, and the requirement was
documented as one line among ~170 in `.env.example` with no mention in the README's Deployment
section — so a default/naive deployment (the stock `docker-compose.yml` exposes the app
directly on port 8000, no TLS termination) silently ran HTTP-only. Anyone on the same untrusted
network as a user (e.g. shared/open wifi) could passively capture their session cookie.

## Fix

1. **Startup check** — `backend/main.py` raises `RuntimeError` at import time if `HTTPS_ONLY`
   isn't `"true"` (case-insensitive) and neither `DEBUG=true` nor `TWITCH_LOCAL_DEV=true` is
   set. It reuses the `_is_dev` flag and `_https_only` value the `SECRET_KEY` check and
   `SessionMiddleware` already use, and runs directly after the `ENV=production` and
   `SECRET_KEY` checks, so errors surface in this order:
   1. `ENV=production` with `DEBUG=true` / `TWITCH_LOCAL_DEV=true` (issue #136)
   2. `ENV=production` with a `SECRET_KEY` shorter than 32 characters (issue #136)
   3. `SECRET_KEY` unset outside local dev
   4. `HTTPS_ONLY` not `"true"` outside local dev (this check)

   Message: `[SECURITY] HTTPS_ONLY is not set. Session cookies would be sent without the
   Secure flag, ... Set HTTPS_ONLY=true once the app is behind a TLS-terminating reverse proxy
   (nginx, Caddy, etc.). To bypass this check in local dev, set DEBUG=true or
   TWITCH_LOCAL_DEV=true.`
2. **README** — the Deployment section has a "Production requires HTTPS" subsection stating
   that production needs a TLS-terminating reverse proxy and `HTTPS_ONLY=true`.
3. **`.env.example`** — the `HTTPS_ONLY` comment says it must be set in production and that
   the app refuses to start without it.

### Interaction with `ENV=production`

With `ENV=production` (issue #136) the app already refuses to start if `DEBUG=true` or
`TWITCH_LOCAL_DEV=true` is set, so neither bypass is available there: a production
deployment must set `HTTPS_ONLY=true`. Without `ENV=production`, the bypasses work as before.

`TWITCH_LOCAL_DEV=true` works as a bypass only while `SECRET_KEY` is unset: the lifespan
refuses to start when `TWITCH_LOCAL_DEV=true` and `SECRET_KEY` are both set. The import-time
check passes, but the server still fails at startup. Use `DEBUG=true` when you have a
`SECRET_KEY`.

The table assumes a valid `SECRET_KEY` (set, and 32+ characters under `ENV=production`). A
missing or short key fails first, with its own error.

| `ENV` | Dev bypass | `HTTPS_ONLY` | Result |
|---|---|---|---|
| unset | none | unset / not `true` | `RuntimeError` (HTTPS_ONLY) |
| unset | none | `true` | starts |
| unset | `DEBUG=true` (or `TWITCH_LOCAL_DEV=true` with `SECRET_KEY` unset) | any | starts (cookies `Secure` only if `HTTPS_ONLY=true`) |
| `production` | any set | any | `RuntimeError` (dev flag) |
| `production` | none | unset | `RuntimeError` (HTTPS_ONLY) |
| `production` | none | `true` | starts (with 32+ char `SECRET_KEY`) |

### Tests and CI

- `backend/tests/conftest.py` sets `DEBUG=true` via `setdefault` before any import, so the
  pytest suite is unaffected.
- `_run_import_main` in `test_issue_118_https_enforcement.py` strips `HTTPS_ONLY` (and the
  dev flags) from the inherited env, and each test passes the value it needs.
- `_run_import_main` in `test_issue_136_security_audit_3.py` sets `HTTPS_ONLY=true` so its
  `ENV` / `SECRET_KEY` guard tests are not masked by this check.
- `docker-compose.dev.yml` sets `DEBUG=true`, so local dev over plain http still starts.
- `.github/workflows/ui-tests.yml` writes `DEBUG=true` into the generated `.env`.
- The Docker/compose health check hits `http://localhost:8000/health` inside the container.
  `HTTPS_ONLY` sets cookie flags and HSTS but does not redirect, so it keeps working.

## Operational note

This is a breaking startup check for any deployment that hasn't already set `HTTPS_ONLY=true`.
Before deploying this fix to a live environment, confirm `HTTPS_ONLY=true` is set there **and**
that the deployment genuinely sits behind a TLS-terminating reverse proxy — setting the flag
without real TLS termination in front of it means the `Secure` cookie flag is set on a
connection that's still plain HTTP, which breaks login entirely (browsers refuse to send
`Secure` cookies over HTTP).

## Debugging "app refuses to start"

If the app raises `RuntimeError: [SECURITY] HTTPS_ONLY is not set...` on startup, either:
- Set `HTTPS_ONLY=true` (only correct once a TLS-terminating reverse proxy is actually in
  front of the app), or
- For local development only, set `DEBUG=true` (or `TWITCH_LOCAL_DEV=true` with `SECRET_KEY`
  unset) instead, or use `docker-compose.dev.yml`, which sets `DEBUG=true`.
