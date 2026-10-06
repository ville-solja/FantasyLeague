# Security Headers

A Starlette middleware layer injects HTTP security response headers on every response,
addressing common findings from vulnerability scanners (Nikto, OWASP ZAP, etc.).

---

## Headers Applied

| Header | Value | Condition |
|---|---|---|
| `X-Content-Type-Options` | `nosniff` | Always |
| `Referrer-Policy` | `strict-origin-when-cross-origin` | Always |
| `Content-Security-Policy` | `frame-ancestors 'self' https://www.twitch.tv https://*.ext-twitch.tv` | Always |
| `Strict-Transport-Security` | `max-age=31536000; includeSubDomains` | Only when `HTTPS_ONLY=true` |

### Why `frame-ancestors` instead of `X-Frame-Options`

`X-Frame-Options` is deprecated. The equivalent CSP directive `frame-ancestors` provides
the same protection and is understood by all current browsers. The policy allows framing
from `twitch.tv` and `*.ext-twitch.tv` because the Twitch panel extension embeds the app
in an iframe on Twitch pages.

### Why `Strict-Transport-Security` is conditional

HSTS must only be sent over HTTPS connections. Sending it over plain HTTP causes browsers
to refuse future plain-HTTP requests, which breaks local development. The header is only
added when `HTTPS_ONLY=true`, which indicates the app is behind an HTTPS reverse proxy.
`HTTPS_ONLY` is itself required outside local dev (the app refuses to start without it
unless `DEBUG=true` or `TWITCH_LOCAL_DEV=true`; see `https-enforcement.md`), so in practice
HSTS is only absent in local development.

---

## CORS Configuration

`CORSMiddleware` no longer uses a wildcard (issue #136). Its settings are:

- `allow_origin_regex=r"^https://[a-z0-9]+\.ext-twitch\.tv$"`. The Twitch panel extension is served from `https://<client-id>.ext-twitch.tv`, a different origin, and calls `/twitch/*` endpoints with an `Authorization` header carrying a Twitch-signed JWT.
- `allow_origins` holds the parsed, comma-separated `CORS_EXTRA_ORIGINS` list, empty by default. Set it to `http://localhost:8080` for Twitch Local Test. It is read at startup.
- `allow_credentials=False`. Browsers never attach session cookies to allowed cross-origin requests. All `/twitch/*` endpoints authenticate via JWT (`verify_twitch_jwt`), not cookies.

Any other origin gets no `Access-Control-Allow-Origin` header. The main site is same-origin and needs no CORS.

---

## Origin Check (CSRF)

`OriginCheckMiddleware` refuses `POST`, `PUT`, `PATCH` and `DELETE` requests outside `/twitch/` (plus `POST /twitch/merge/confirm` and `POST /twitch/disconnect`, which use the session cookie; `POST /twitch/link-code` until #160 retired it) with `403 {"detail": "Cross-origin request refused"}` when the `Origin` header, or the `Referer` if there is no `Origin`, names a host other than the request's `Host` header or the host of `APP_BASE_URL`. Requests with neither header pass. `CSRF_ORIGIN_CHECK=false` turns it off. The main case it covers is a page on a sibling subdomain, which `SameSite=Lax` does not stop. See [Security Audit 3](security-audit-3.md) for details.

---

## Implementation

`SecurityHeadersMiddleware` and `OriginCheckMiddleware` are `BaseHTTPMiddleware` subclasses
registered in `backend/main.py` after `SessionMiddleware` and before `CORSMiddleware`, so
`CORSMiddleware` answers preflights before the Origin check runs. `SecurityHeadersMiddleware` reads the
already-resolved `_https_only` boolean (derived from the `HTTPS_ONLY` env var) to decide
whether to include `Strict-Transport-Security`.

---

## Global Exception Handler

`backend/main.py` registers `@app.exception_handler(Exception)`, catching any exception not
already turned into an `HTTPException`. It logs the full traceback server-side
(`logger.exception(...)`) and returns a generic `JSONResponse({"detail": "Internal server
error"}, status_code=500)` to the caller. Without this, Starlette's default handler returns a
**plain-text** body for unhandled exceptions, which breaks every frontend caller's
`res.json()` — this was a real bug (`Unexpected token 'I', "Internal S"...`) traced to a league
ingest crashing on an empty OpenDota response; fixed both at the source and with this handler
as a systemic backstop for any future unhandled exception.

---

## Session Cookie

`SessionMiddleware` is configured with `same_site="lax"`, `path="/"` and a `max_age` equal to the
larger session absolute limit (default 2592000, 30 days; issue #117), in addition to the
`HTTPS_ONLY`-gated `Secure` flag described above. Under `HTTPS_ONLY=true` the cookie is named
`__Host-session`; the server enforces the real session limits (see `reference/longer-sessions.md`). See `core/auth.md`'s
"Session Cookie" section for the `SECRET_KEY` requirement.

