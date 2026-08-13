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

---

## CORS Configuration

The app uses `allow_origins=["*"]` in `CORSMiddleware`. This is intentional:

- The Twitch panel extension is served from `*.ext-twitch.tv`, a different origin. It
  must be able to call `/twitch/*` endpoints using an `Authorization` header carrying a
  Twitch-signed JWT.
- `allow_credentials=False` is set alongside the wildcard. This means the browser will
  never attach session cookies to cross-origin requests, so the wildcard does not expose
  session-protected endpoints to cross-origin abuse.
- All `/twitch/*` endpoints authenticate via JWT (`verify_twitch_jwt`), not cookies.
  Cross-origin callers cannot impersonate a logged-in user.

If the Twitch extension is removed in the future, `allow_origins` should be restricted
to the app's own origin and `allow_credentials` may be set to `True`.

---

## Implementation

`SecurityHeadersMiddleware` is a `BaseHTTPMiddleware` subclass registered in
`backend/main.py` after `SessionMiddleware` and before `CORSMiddleware`. It reads the
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

`SessionMiddleware` is configured with `same_site="lax"` and `max_age=86400` (24 hours), in
addition to the `HTTPS_ONLY`-gated `Secure` flag described above. See `core/auth.md`'s
"Session Cookie" section for the `SECRET_KEY` requirement.

