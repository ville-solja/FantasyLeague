# Plan: HTTPS Enforcement

## Context
Issue #118 reported that session cookies — including an admin's — can be intercepted by
anyone on the same untrusted network (shared/open wifi) as a victim, because nothing in the
app enforces HTTPS or requires the `Secure` cookie flag to be enabled. `SessionMiddleware`
(`backend/main.py`) only sets `Secure` when `HTTPS_ONLY=true` is explicitly set — a single
optional env var, documented as one line among ~170 in `.env.example`, with no mention at all
in the README's Deployment section. The default `docker-compose.yml` exposes the app directly
on port 8000 with no TLS termination, so a naive/default deployment is HTTP-only by default.

This plan implements both parts of the issue's recommendation:
1. Make the README's Deployment section explicitly state that production deployments must sit
   behind a TLS-terminating reverse proxy with `HTTPS_ONLY=true` set — not buried as one config
   line among many.
2. Fail loudly at startup if `HTTPS_ONLY` is unset and the app isn't in local-dev mode,
   mirroring the exact pattern the existing `SECRET_KEY` check already uses (same file, same
   `_is_dev` flag, same dev-bypass conditions: `DEBUG=true` or `TWITCH_LOCAL_DEV=true`).

**Operational risk that must be called out clearly, since this is a real production app:**
the startup check is a breaking change for any currently-running deployment that hasn't
explicitly set `HTTPS_ONLY=true` yet — which, given this is exactly the bug being fixed, is
plausibly the current state of the live Kanaliiga deployment. **`HTTPS_ONLY=true` must be set
on the live deployment's environment at or before the moment this fix is deployed, or the app
will refuse to start.** This isn't optional cleanup — it's a required, coordinated step, and is
repeated in this plan's Verification section so it isn't missed. *Resolves GitHub issue #118.*

## User Stories

### Fail Loudly at Startup if HTTPS Isn't Enforced
**User story**
As an operator, I want the app to refuse to start in a production-like configuration if
`HTTPS_ONLY` isn't set, so that a misconfigured deployment can't silently serve session cookies
over unencrypted connections.

**Acceptance criteria**
- On startup, if `HTTPS_ONLY` is not `"true"` and neither `DEBUG=true` nor
  `TWITCH_LOCAL_DEV=true` is set, the app raises a clear `RuntimeError` and refuses to start —
  mirroring the existing `SECRET_KEY` check's exact structure and message style
- Setting `DEBUG=true` or `TWITCH_LOCAL_DEV=true` (the same existing local-dev bypasses) skips
  this check, so local development is unaffected
- The error message states what to do: set `HTTPS_ONLY=true` once behind a TLS-terminating
  reverse proxy, or use one of the local-dev bypasses
- The existing test suite (which imports `main.py` with `DEBUG=true` set) is unaffected by this
  new check

### Prominent Deployment Documentation
**User story**
As an operator setting up a new deployment, I want the README to clearly state upfront that
production requires a TLS-terminating reverse proxy and `HTTPS_ONLY=true`, so I don't discover
this requirement only when the app refuses to start.

**Acceptance criteria**
- `README.md`'s Deployment section explicitly states the TLS/reverse-proxy requirement for
  production, not just a passing mention
- `.env.example`'s `HTTPS_ONLY` comment is strengthened to match `SECRET_KEY`'s existing
  "must be set in production" framing, rather than reading as one optional setting among many
- A new reference doc explains the vulnerability this closes and the startup-check mechanics
  for anyone debugging why their deployment won't start

---

## Implementation

### Critical Files
| File | Change |
|---|---|
| `backend/main.py` | Extend the existing `SECRET_KEY` startup-validation block to also check `HTTPS_ONLY` |
| `README.md` | Add an explicit TLS/reverse-proxy requirement to the Deployment section |
| `.env.example` | Strengthen the `HTTPS_ONLY` comment |
| `markdown/features/reference/https-enforcement.md` | New reference doc (stub created by product-planner) |

No model changes, no migrations, no new env vars (`HTTPS_ONLY` already exists).

### Step 1 — Startup check
In `backend/main.py`, immediately after the existing `_https_only = os.getenv("HTTPS_ONLY", "false").lower() == "true"` line (which comes right after the `SECRET_KEY` block and already has `_is_dev` computed above it — reuse it, don't recompute):
```python
if not _https_only and not _is_dev:
    raise RuntimeError(
        "[SECURITY] HTTPS_ONLY is not set. Session cookies would be sent without the Secure "
        "flag, making them interceptable over unencrypted connections. Set HTTPS_ONLY=true "
        "once the app is behind a TLS-terminating reverse proxy (nginx, Caddy, etc.). "
        "To bypass this check in local dev, set DEBUG=true or TWITCH_LOCAL_DEV=true."
    )
```

### Step 2 — README
Add a short, explicit subsection under `## Deployment`:
```markdown
### Production requires HTTPS

Production deployments must run behind a TLS-terminating reverse proxy (nginx, Caddy, etc.)
and set `HTTPS_ONLY=true`. The app refuses to start without it (unless `DEBUG=true` or
`TWITCH_LOCAL_DEV=true` for local dev) — session cookies are only ever safe to send without
the `Secure` flag on an encrypted connection.
```

### Step 3 — `.env.example`
Update the existing `HTTPS_ONLY` comment to match `SECRET_KEY`'s framing:
```
# Set to "true" once the app is behind an HTTPS reverse proxy (e.g. nginx/caddy).
# Enables the Secure flag on session cookies. Must be set in production — the app refuses
# to start without it unless DEBUG=true or TWITCH_LOCAL_DEV=true.
# HTTPS_ONLY=true
```

### Step 4 — Fill in the feature doc stub
Update `markdown/features/reference/https-enforcement.md` with final confirmed behavior.

---

## Verification
- `cd backend && DEBUG=true python -m pytest tests/ -v` — the full suite must stay green;
  confirm every test path that imports `main.py` runs with `DEBUG=true` (or equivalent) already
  set, since this new check would otherwise block test collection/startup entirely
- Manually confirm: starting the app with `HTTPS_ONLY` unset and no dev bypass raises the new
  `RuntimeError` immediately; setting `HTTPS_ONLY=true`, or either dev bypass, allows normal
  startup
- **Before this ships to the live deployment: confirm `HTTPS_ONLY=true` is already set in that
  environment's configuration.** If it isn't, set it first (and confirm the deployment is
  actually behind a TLS-terminating proxy — setting the flag without real TLS termination in
  front of it would mean the `Secure` cookie flag is set on a connection that's still plain
  HTTP, breaking login entirely, since browsers refuse to send `Secure` cookies over HTTP).
