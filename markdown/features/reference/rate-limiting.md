# Rate Limiting

Per-IP request-rate limits across the app, with stricter limits on `/login`, `/register`, and
`/forgot-password`, plus a per-username failed-login lockout on `/login` independent of source
IP.

*(see `markdown/plans/plan-issue-121-rate-limiting.md`, resolves GitHub issue #121)*

---

## Approach

Implemented with `slowapi`, an in-memory rate limiter — sufficient because the app runs as a
single uvicorn process with no `--workers` flag, so no shared-state backend (e.g. Redis) is
needed. The shared `Limiter` instance lives in `backend/rate_limit.py` (not directly in
`main.py`) so both `main.py` and `backend/routers/auth.py` can import it without a circular
import. Limits are enforced per client IP address (`slowapi.util.get_remote_address`, i.e.
`request.client.host`). slowapi itself never reads `X-Forwarded-For`, but uvicorn's
`--proxy-headers` middleware rewrites `request.client.host` from that header before the limiter
sees it, for peers listed in `FORWARDED_ALLOW_IPS` (see "Trusted proxies" below). Limits apply
via a global middleware baseline
(`SlowAPIMiddleware`, applied to every route with no per-route decorator) plus per-route
`@limiter.limit(...)` decorators on the three sensitive auth endpoints, which override the
global baseline for those routes rather than stacking on top of it.

Exceeding a limit returns HTTP 429 with `{"detail": "Rate limit exceeded: ..."}`, via a custom
`RateLimitExceeded` exception handler registered in `main.py` — matching the app's existing
error response shape rather than slowapi's default `{"error": "..."}` shape.

## Trusted proxies

The per-IP limits are only as good as the client address uvicorn reports. The image sets
`FORWARDED_ALLOW_IPS` to loopback and the private ranges (`10.0.0.0/8`, `172.16.0.0/12`,
`192.168.0.0/16`, `fc00::/7`), so forwarded headers are honoured only from a reverse proxy on the
same host (reaching the published port through Docker's bridge gateway), a proxy container, or a
private load balancer. A client connecting from a public address keeps its own address whatever
`X-Forwarded-For` it sends, and behind a proxy the rightmost untrusted entry wins, so a
client-supplied prefix is ignored.

Before 2026-09-24 the image ran uvicorn with `--forwarded-allow-ips "*"` while
`docker-compose.yml` published port 8000 on all interfaces, so anyone who could reach the port
could pick a fresh IP per request and bypass every per-IP limit here. Never set
`FORWARDED_ALLOW_IPS=*`. Set `APP_BIND_ADDRESS=127.0.0.1` in `.env` when the proxy runs on the same
host, so the port is not reachable from outside at all. Covered by
`backend/tests/test_proxy_trust_and_twitch_uniqueness.py`.

## Endpoints affected

- `POST /login` — stricter per-IP limit (`RATE_LIMIT_LOGIN`) plus an independent per-username
  lockout (`backend/routers/auth.py`'s `_is_locked_out`/`_record_failed_login`/
  `_clear_failed_logins`) after `LOGIN_LOCKOUT_THRESHOLD` failed attempts against one username
  within `LOGIN_LOCKOUT_WINDOW_SECONDS`, regardless of source IP. The lockout check runs before
  the DB is queried or bcrypt is invoked, and returns the same generic 429 message
  (`"Too many failed login attempts. Please try again later."`) whether or not the submitted
  username exists — the failed-attempt counter is keyed by the submitted username string itself,
  so a nonexistent username accumulates and locks out identically to a real one. A successful
  login clears that username's counter.
- `POST /reauth` (issue #117) — shares `RATE_LIMIT_LOGIN` and the same per-username lockout as
  `/login`: a wrong password counts as a failed attempt, a locked-out username gets the same
  429, and a correct password clears the counter.
- `POST /register` — stricter per-IP limit (`RATE_LIMIT_REGISTER`)
- `POST /forgot-password` — stricter per-IP limit (`RATE_LIMIT_FORGOT_PASSWORD`); its existing
  enumeration-safe behavior (`{"status": "ok"}` always, bcrypt timing equalization) is unchanged
- `POST /reset-password` — per-IP limit (`RATE_LIMIT_RESET_PASSWORD`, issue #135) against
  reset-code guessing
- `POST /redeem` — per-user limit (`RATE_LIMIT_REDEEM`, issue #135) against promo-code guessing,
  keyed by user via `key_by_user_or_ip` (`user:{id}`, from `request.state.session_user_id`,
  which `get_current_user` sets; the cookie carries only a session ID since #117)
- `GET /cards/{card_id}/image` — per-IP limit (`RATE_LIMIT_CARD_IMAGE`, issue #135); the endpoint
  is public and renders a PNG with Pillow on every call
- `GET /auth/twitch/start` and `GET /auth/twitch/callback` — per-IP limit each
  (`RATE_LIMIT_TWITCH_OAUTH`, issue #160). They replaced the retired `POST /twitch/link`
  (`RATE_LIMIT_TWITCH_LINK`, #135, against link-code guessing)
- Twitch panel game routes (issue #157) — Join per viewer (`RATE_LIMIT_TWITCH_JOIN`, keyed by the
  opaque Twitch id through `key_by_twitch_viewer_or_ip`) and per IP (`RATE_LIMIT_TWITCH_JOIN_IP`,
  also on both draws); draws, roster changes and Leave per viewer (`RATE_LIMIT_TWITCH_ACTION`)
- Roster activate/deactivate/swap/reorder — per-user limit (`RATE_LIMIT_ROSTER_MUTATION`,
  issue #124)
- Every other route — the global baseline (`RATE_LIMIT_GLOBAL`) applies automatically via
  `SlowAPIMiddleware`, with no per-route opt-in needed

## Out of scope

Per-account cooldown on `/forgot-password` independent of source IP (GitHub issue #122) and
the endpoint overwriting the real password before verifying email ownership (GitHub issue
#123) are separate, narrower fixes tracked elsewhere — this feature only adds IP-based rate
limiting.

## Configuration

| Variable | Default | Description |
|---|---|---|
| `RATE_LIMIT_GLOBAL` | `200/minute` | Baseline per-IP limit applied to every route |
| `RATE_LIMIT_LOGIN` | `5/minute` | Stricter per-IP limit on `POST /login` |
| `RATE_LIMIT_REGISTER` | `5/minute` | Stricter per-IP limit on `POST /register` |
| `RATE_LIMIT_FORGOT_PASSWORD` | `3/minute` | Stricter per-IP limit on `POST /forgot-password` |
| `RATE_LIMIT_RESET_PASSWORD` | `10/minute` | Per-IP limit on `POST /reset-password` |
| `RATE_LIMIT_REDEEM` | `5/minute` | Per-user limit on `POST /redeem` |
| `RATE_LIMIT_CARD_IMAGE` | `60/minute` | Per-IP limit on `GET /cards/{card_id}/image` |
| `RATE_LIMIT_TWITCH_OAUTH` | `10/minute` | Per-IP limit on each of `GET /auth/twitch/start` and `/auth/twitch/callback` (#160; `RATE_LIMIT_TWITCH_LINK` retired with `POST /twitch/link`) |
| `RATE_LIMIT_TWITCH_JOIN` | `10/minute` | Per-viewer limit on `POST /twitch/join` |
| `RATE_LIMIT_TWITCH_JOIN_IP` | `60/minute` | Per-IP limit on `POST /twitch/join`, `/twitch/draw` and `/twitch/draw/booster/{team_id}` |
| `RATE_LIMIT_TWITCH_ACTION` | `30/minute` | Per-viewer limit on Twitch panel draws, roster changes and Leave |
| `RATE_LIMIT_ROSTER_MUTATION` | `30/minute` | Per-user limit on roster mutations |
| `LOGIN_LOCKOUT_THRESHOLD` | `10` | Failed login attempts against one username before lockout |
| `LOGIN_LOCKOUT_WINDOW_SECONDS` | `300` | Rolling window the lockout threshold is counted over |

All values are read once at process startup (module-import time in `backend/rate_limit.py`,
`backend/routers/auth.py`, `backend/routers/cards.py`, `backend/routers/admin_users.py` and
`backend/twitch.py`); changing them requires a restart.

Handlers that other code or tests call as plain functions (`redeem_code`, `get_card_image`,
`link_account`, the roster mutations) are split into the undecorated function and a thin
`*_route` wrapper that FastAPI registers. The wrapper carries the `request: Request` parameter
slowapi needs, so direct callers keep their existing signature.

## Response shape

Any rate limit (global or per-route) exceeded via slowapi returns:
```json
{"detail": "Rate limit exceeded: 5 per 1 minute"}
```
The per-username login lockout returns the same status code with a fixed generic message:
```json
{"detail": "Too many failed login attempts. Please try again later."}
```

## State and persistence

Both the slowapi limiter's per-IP counters and the per-username lockout tracker are in-memory
only (a single-process assumption, same as the rest of this app's background jobs). Counters
reset on process restart — an acceptable tradeoff at this app's scale, matching the reasoning
used for the in-memory ingest/enrichment state elsewhere in the codebase.
