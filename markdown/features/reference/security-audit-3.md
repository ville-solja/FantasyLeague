# Security Audit 3

Hardening from the third external security review (GitHub issue #136). The review found no serious flaws. These changes close the small remaining gaps it pointed at. The per-finding triage is in `markdown/plans/plan-issue-136-security-audit-3.md`.

---

## Cross-origin request check

The session cookie is already `SameSite=Lax`, and FastAPI rejects non-JSON bodies, so ordinary cross-site forgery is blocked. The remaining gap is pages on sibling subdomains (for example `test.kana-cards.com`), which count as the same site and so receive the cookie.

`OriginCheckMiddleware` in `backend/main.py` handles this:

- Applies to `POST`, `PUT`, `PATCH` and `DELETE` only. `GET`, `HEAD` and `OPTIONS` are never blocked, and CORS preflights are answered by `CORSMiddleware` first.
- Paths starting with `/twitch/` are exempt. They authenticate with a Twitch JWT in the `Authorization` header and are called from the extension origin. The exceptions are the session-cookie routes in `_COOKIE_AUTH_TWITCH_PATHS`, checked like any other cookie route: `POST /twitch/merge/confirm` and `POST /twitch/disconnect` since #160 (originally `POST /twitch/link-code`, now retired).
- Reads `Origin`, falling back to `Referer`. When both are absent the request passes (API clients, scripts, tests).
- Allows the request when the source host (lower-cased, with port when non-default) equals the request's `Host` header or the host of `APP_BASE_URL`. Otherwise it returns `403 {"detail": "Cross-origin request refused"}`. An unparseable or opaque `Origin` such as `null` counts as foreign.
- `CSRF_ORIGIN_CHECK` and `APP_BASE_URL` are read on every request.

If a reverse proxy rewrites `Host`, same-site requests will get 403. Set `APP_BASE_URL` to the public URL first. Use `CSRF_ORIGIN_CHECK=false` only as a last resort.

## Username allowlist

`check_username()` in `backend/auth.py` enforces `^[A-Za-z0-9_-]+$`. It is the field validator on `RegisterBody` (`POST /register`) and `UpdateUsernameBody` (`PUT /profile/username`), which also keep the 1–64 length limit. It replaces the earlier `< > " '` blocklist. A rejected name gets 422, and the message lists the allowed characters: letters A-Z and a-z, digits 0-9, underscore and hyphen.

`LoginBody` has no charset check, so existing accounts whose names fall outside the pattern still log in and keep their name until they change it. The register and profile forms show the allowed characters under the username field.

## CORS

`CORSMiddleware` allows origins matching `^https://[a-z0-9]+\.ext-twitch\.tv$` (the Twitch extension iframe), plus any comma-separated origins in `CORS_EXTRA_ORIGINS`. The extra origins are read at startup. `allow_credentials` stays `False`. The main site is same-origin and needs no CORS.

## Production guards

At import time, `backend/main.py` checks `ENV`. When it is `production` (case-insensitive), startup fails with a `RuntimeError` if:

- `DEBUG=true` or `TWITCH_LOCAL_DEV=true` is set, even when `SECRET_KEY` is set
- `SECRET_KEY` is shorter than 32 characters

The CI workflow `.github/workflows/unit-tests.yml` runs `pip-audit -r backend/requirements.txt` after installing dependencies. A known vulnerability fails the job.

## Configuration

| Variable | Default | Description |
|---|---|---|
| `CSRF_ORIGIN_CHECK` | `true` | Set `false` to disable the cross-origin check, for example if the proxy rewrites `Host` |
| `CORS_EXTRA_ORIGINS` | *(empty)* | Extra comma-separated CORS origins, e.g. `http://localhost:8080` for Twitch Local Test |
| `APP_BASE_URL` | *(empty)* | Its host is accepted by the cross-origin check alongside the request `Host` |
| `ENV` | *(empty)* | `production` turns on the startup guards above |

## Tests

`backend/tests/test_issue_136_security_audit_3.py`
