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
`@limiter.limit(...)` (or `shared_limit`) decorators on the auth endpoints, redeem, card images,
the Twitch and Steam routes, roster changes, card actions and every other player write route
(see "Endpoints affected"); a route-level limit overrides the global baseline for that route
rather than stacking on top of it.

Exceeding a limit returns HTTP 429 with `{"detail": "Too many requests. Wait a moment and try
again."}` and a `Retry-After` header, via a custom `RateLimitExceeded` exception handler
registered in `main.py` — matching the app's existing error response shape rather than slowapi's
default `{"error": "..."}` shape. See "Response shape" below.

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
- `GET /auth/steam/start`, `GET /auth/steam/callback` and `POST /auth/steam/signup` — per-IP limit
  each (`RATE_LIMIT_STEAM_CALLBACK`, issue #150; one variable covers all three). See
  `reference/steam-login.md`
- Twitch panel game routes (issue #157) — Join per viewer (`RATE_LIMIT_TWITCH_JOIN`, keyed by the
  opaque Twitch id through `key_by_twitch_viewer_or_ip`) and per IP (`RATE_LIMIT_TWITCH_JOIN_IP`,
  also on both draws); draws, roster changes and Leave per viewer (`RATE_LIMIT_TWITCH_ACTION`).
  `POST /twitch/heartbeat` (issue #171) is limited per viewer (`RATE_LIMIT_TWITCH_ACTION`) and per
  IP (`RATE_LIMIT_TWITCH_JOIN_IP`). `GET /twitch/ping` (issue #180) is limited per IP
  (`RATE_LIMIT_TWITCH_JOIN_IP`). `GET /twitch/panel` is limited per viewer
  (`RATE_LIMIT_TWITCH_ACTION`) and per IP (`RATE_LIMIT_TWITCH_JOIN_IP`), and its body is cached
  in memory for `TWITCH_PANEL_CACHE_SECONDS` (default 30); see
  `reference/twitch-extension-setup-followups.md`
- Roster activate/deactivate/swap/reorder and `PUT /roster` (#186) — per-user limit
  (`RATE_LIMIT_ROSTER_MUTATION`, issue #124)
- `POST /draw`, `POST /draw/booster/{team_id}` and `POST /roster/{card_id}/reroll` (issue #184) —
  one shared per-user budget (`RATE_LIMIT_CARD_ACTION`, keyed by `key_by_user_or_ip`) and one
  shared per-IP budget (`RATE_LIMIT_CARD_ACTION_IP`), through slowapi's `shared_limit` with the
  scopes `card_action` and `card_action_ip`, so mixing the three actions doesn't multiply the
  rate. The limit is checked after login is resolved and before the handler runs, so a refused
  request spends no tokens and creates no card. See `reference/action-throttling.md`
- Other player write routes (issue #184) — per-user limit (`RATE_LIMIT_USER_ACTION`) on
  `PUT /profile/username`, `PUT /profile/password`,
  `POST /weekly-summary/{week_id}/reveal`, `POST /weekly-summary/reveal-all`,
  `POST /weekly-summary/seen`, `POST /weekly-summary/prompted`, `POST /claim-events`,
  `POST /notifications/{notification_id}/dismiss`, `DELETE /sessions/{session_id}`,
  `POST /logout-everywhere`, `POST /twitch/merge/confirm`, `POST /twitch/disconnect` and
  `POST /profile/steam/unlink`. Each route counts on its own
- `POST /simulate/{match_id}` (issue #184) — per-IP limit (`RATE_LIMIT_SIMULATE`); the endpoint
  is public and scores a whole match per call
- `POST /twitch/mvp` (issue #184) — per-IP limit (`RATE_LIMIT_TWITCH_JOIN_IP`)
- Every other route — the global baseline (`RATE_LIMIT_GLOBAL`) applies automatically via
  `SlowAPIMiddleware`, with no per-route opt-in needed. For write routes this is deliberate and
  narrow: admin routes (under `/admin` or guarded by `require_admin`; destructive ones also need
  a recent re-auth), `POST /logout`, and `main.py`'s 404 catch-alls for unknown `/twitch/*` and
  `/auth/steam/*` paths. `backend/tests/test_issue_184_action_throttling.py` lists every
  non-admin `POST`/`PUT`/`PATCH`/`DELETE` route and fails when one has no route-level limit and
  is not in its commented `ALLOWED_GLOBAL_ONLY` allowlist

A route-level limit replaces the global baseline for that route; it does not stack on top of it.

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
| `RATE_LIMIT_STEAM_CALLBACK` | `10/minute` | Per-IP limit on each of `GET /auth/steam/start`, `GET /auth/steam/callback` and `POST /auth/steam/signup` (#150) |
| `RATE_LIMIT_TWITCH_JOIN` | `10/minute` | Per-viewer limit on `POST /twitch/join` |
| `RATE_LIMIT_TWITCH_JOIN_IP` | `60/minute` | Per-IP limit on `POST /twitch/join`, `/twitch/draw`, `/twitch/draw/booster/{team_id}`, `/twitch/heartbeat`, `GET /twitch/panel` and `GET /twitch/ping` (#180) |
| `RATE_LIMIT_TWITCH_ACTION` | `30/minute` | Per-viewer limit on Twitch panel draws, heartbeats, `GET /twitch/panel`, roster changes and Leave |
| `RATE_LIMIT_ROSTER_MUTATION` | `30/minute` | Per-user limit on roster mutations |
| `RATE_LIMIT_CARD_ACTION` | `20/minute` | Per-user budget shared by `POST /draw`, `POST /draw/booster/{team_id}` and `POST /roster/{card_id}/reroll` (#184) |
| `RATE_LIMIT_CARD_ACTION_IP` | `60/minute` | Per-IP budget shared by the same three routes (#184) |
| `RATE_LIMIT_USER_ACTION` | `60/minute` | Per-user limit on each other player write route listed above (#184) |
| `RATE_LIMIT_SIMULATE` | `20/minute` | Per-IP limit on `POST /simulate/{match_id}` (#184) |
| `MAX_REQUEST_BODY_BYTES` | `65536` | Largest accepted request body; larger gets 413 before any route runs. A non-numeric or non-positive value means 65536 (#184) |
| `LOGIN_LOCKOUT_THRESHOLD` | `10` | Failed login attempts against one username before lockout |
| `LOGIN_LOCKOUT_WINDOW_SECONDS` | `300` | Rolling window the lockout threshold is counted over |

All values are read once at process startup (module-import time in `backend/rate_limit.py`,
`backend/routers/auth.py`, `backend/routers/cards.py`, `backend/routers/admin_users.py`,
`backend/twitch.py`, `backend/twitch_oauth.py`, `backend/steam_openid.py` and, for
`MAX_REQUEST_BODY_BYTES`, `backend/main.py`); changing them requires a restart. The #184 limits
are defined together in `backend/rate_limit.py`.

Handlers that other code or tests call as plain functions (`redeem_code`, `get_card_image`,
the roster mutations, and since #184 `draw_card`, `draw_booster`,
`reroll_modifiers`, `update_username`, `update_player_id`, `change_password`, the four Weekly
Report actions, `simulate_match` and the Twitch `set_mvp`) are split into the undecorated function and a thin
`*_route` wrapper that FastAPI registers. The wrapper carries the `request: Request` parameter
slowapi needs, so direct callers keep their existing signature.

## Response shape

Any rate limit (global or per-route) exceeded via slowapi returns 429 with a `Retry-After`
header (the limit's window in seconds, e.g. `60` for a `/minute` limit) and:
```json
{"detail": "Too many requests. Wait a moment and try again."}
```
The website shows this text in the action's status area (draw, booster, reroll and roster
changes); the Twitch panel keeps its own neutral message.

Each refusal logs one INFO line, `Rate limited: <METHOD> <route template> (<user|ip|twitch>)`,
for example `Rate limited: POST /roster/{card_id}/reroll (user)`. It never names the client IP
or the user id, and is written at most once per key and route per minute (the key is kept only
as a SHA-256 hash in memory). slowapi's own warning, which does name the key, is filtered out.

A body over `MAX_REQUEST_BODY_BYTES` gets 413 `{"detail": "Request too large"}`.

The per-username login lockout returns the same status code with a fixed generic message:
```json
{"detail": "Too many failed login attempts. Please try again later."}
```

## State and persistence

Both the slowapi limiter's counters (per IP, per user and per Twitch viewer) and the per-username lockout tracker are in-memory
only (a single-process assumption, same as the rest of this app's background jobs). Counters
reset on process restart — an acceptable tradeoff at this app's scale, matching the reasoning
used for the in-memory ingest/enrichment state elsewhere in the codebase.

## Layered protection

The app's limits protect the database from a busy account or script. They can't stop a flood:
every refused request has still crossed the network and been parsed by the one app process.
Run these layers in order, outermost first.

### 1. Edge (optional CDN or WAF)

The only layer that absorbs volumetric floods. A CDN or WAF such as Cloudflare in front of the
server takes bandwidth floods and SYN floods before they reach the host, and can challenge
suspicious clients. When one is used:
- let only its address ranges reach the proxy (firewall), so it can't be bypassed;
- restore the real client address at the proxy (nginx `real_ip_header CF-Connecting-IP` with
  `set_real_ip_from` for each Cloudflare range). Otherwise every player shares a few Cloudflare
  addresses and the per-IP limits below lock out real players.

### 2. Reverse proxy

nginx or Caddy terminates TLS and should:
- limit request rates per IP (`limit_req` in nginx, the `rate_limit` module in Caddy), at or
  above the app's `RATE_LIMIT_GLOBAL` (200/minute) so normal throttling still gets the app's
  message and only floods are cut at the proxy;
- limit concurrent connections per IP (`limit_conn` in nginx);
- cap body size at the app's `MAX_REQUEST_BODY_BYTES` (64 KiB);
- set read and idle timeouts, so slow-client attacks (slowloris, slow bodies) can't hold
  connections open.

nginx, with values matching the app's defaults:

```nginx
limit_req_zone  $binary_remote_addr zone=fantasy_req:10m rate=200r/m;
limit_conn_zone $binary_remote_addr zone=fantasy_conn:10m;

server {
    listen 443 ssl;
    server_name fantasy.example.com;

    client_max_body_size  64k;   # MAX_REQUEST_BODY_BYTES
    client_header_timeout 10s;
    client_body_timeout   10s;
    send_timeout          30s;
    keepalive_timeout     30s;

    location / {
        limit_req  zone=fantasy_req burst=50 nodelay;   # RATE_LIMIT_GLOBAL, with a burst
        limit_conn fantasy_conn 20;
        limit_req_status  429;
        limit_conn_status 429;

        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host              $host;
        proxy_set_header X-Forwarded-For   $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 60s;
    }
}
```

Caddy. `rate_limit` is not built in: build Caddy with the
[caddy-ratelimit](https://github.com/mholt/caddy-ratelimit) module (`xcaddy build --with
github.com/mholt/caddy-ratelimit`). Caddy has no per-IP connection limit; its server timeouts
cover slow clients.

```caddy
{
    order rate_limit before reverse_proxy
    servers {
        timeouts {
            read_header 10s
            read_body   10s
            write       30s
            idle        2m
        }
    }
}

fantasy.example.com {
    request_body {
        max_size 64KB   # MAX_REQUEST_BODY_BYTES
    }
    rate_limit {
        zone per_ip {
            key    {remote_host}
            events 200   # RATE_LIMIT_GLOBAL
            window 1m
        }
    }
    reverse_proxy 127.0.0.1:8000
}
```

### 3. The app

What Kana Cards does on its own, all in one process and in memory:
- the global per-IP baseline (`RATE_LIMIT_GLOBAL`) on every route without its own limit;
- per-user limits on every player action (`RATE_LIMIT_CARD_ACTION`, `RATE_LIMIT_USER_ACTION`,
  `RATE_LIMIT_ROSTER_MUTATION`, `RATE_LIMIT_REDEEM`) plus per-IP limits on card actions,
  `/simulate` and the Twitch panel;
- stricter auth limits (`RATE_LIMIT_LOGIN`, `RATE_LIMIT_REGISTER`, `RATE_LIMIT_FORGOT_PASSWORD`,
  `RATE_LIMIT_RESET_PASSWORD`) and the per-username login lockout;
- the body size cap (`MAX_REQUEST_BODY_BYTES`, 413 before the route runs, with or without
  `Content-Length`);
- atomic token spending (`spend_tokens`), so a burst of draws can't overspend;
- cached hot reads: `GET /twitch/panel` (`TWITCH_PANEL_CACHE_SECONDS`) and the schedule.

### 4. Host and deployment

- `APP_BIND_ADDRESS=127.0.0.1` when the proxy runs on the same host, so port 8000 is not
  reachable from outside and the proxy can't be bypassed.
- Never `FORWARDED_ALLOW_IPS=*`: any client could then pick a fresh address per request and
  escape every per-IP limit (see "Trusted proxies" above).
- A single process (no `--workers`): the limits live in that process's memory.

### What the app can't do

- Absorb bandwidth floods. Refusing a request still costs the network and the process; only
  the edge and the proxy can drop floods cheaply.
- Share limits across several processes or hosts. Each process would count separately, which
  multiplies every limit. Running more than one needs a shared slowapi storage such as Redis.
- Stop many accounts from many addresses acting slowly. Each stays under its own limits; that is
  abuse to handle with moderation tools, not rate limits.
