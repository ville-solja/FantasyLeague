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

1. **Startup check** *(planned)* — `backend/main.py` now raises `RuntimeError` at startup if
   `HTTPS_ONLY` isn't `"true"` and neither `DEBUG=true` nor `TWITCH_LOCAL_DEV=true` is set,
   mirroring the existing `SECRET_KEY` check's exact structure (same `_is_dev` flag, same
   dev-bypass conditions, same message style).
2. **README** *(planned)* — the Deployment section now explicitly states that production
   requires a TLS-terminating reverse proxy and `HTTPS_ONLY=true`, rather than leaving it to be
   discovered via `.env.example`.
3. **`.env.example`** *(planned)* — `HTTPS_ONLY`'s comment strengthened to match `SECRET_KEY`'s
   "must be set in production" framing.

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
- For local development only, set `DEBUG=true` or `TWITCH_LOCAL_DEV=true` instead.
