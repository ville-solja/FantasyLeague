# Plan: Action Throttling

## Context
Card draws, booster draws, rerolls and most other player actions have no limit of their own. Only the global per-IP baseline (`RATE_LIMIT_GLOBAL`, 200/minute) applies, so one account can send up to 200 actions a minute, and one IP can fan out across many accounts. Draws can't overspend, because `spend_tokens` deducts atomically. But each draw is a database write, and SQLite serialises writes, so a scripted burst slows the site for everyone. The issue also asks for best practices against basic denial of service. The app alone can't stop volumetric floods: the reverse proxy or a CDN has to. So this plan does three things:
- tightens the app's own limits: per-user limits on every player action, a size cap on request bodies, and clearer 429 responses;
- adds a test that keeps every new write route limited;
- documents the layered setup operators should run in front of the app.

Assumptions:
- One process: the limits stay in memory (slowapi), per `markdown/features/reference/rate-limiting.md`.
- The defaults below are generous for real play (a player opening a booster pack clicks a few times a minute, not dozens). They can be changed with environment variables.

Resolves GitHub issue #184.

## User Stories

### Throttle Card Actions per Player
**User story**
As the operator, I want each account's card draws, booster draws and rerolls limited per minute so that a script can't hammer the database through one account.

**Acceptance criteria**
- `POST /draw`, `POST /draw/booster/{team_id}` and `POST /roster/{card_id}/reroll` share a per-user limit `RATE_LIMIT_CARD_ACTION` (default `20/minute`), keyed by `key_by_user_or_ip`
- They also keep a per-IP limit (`RATE_LIMIT_CARD_ACTION_IP`, default `60/minute`), so many accounts behind one address can't multiply the rate
- The 21st card action from one account within a minute gets 429; other accounts are unaffected
- A refused request spends no tokens and creates no card

### Every Player Action Has a Limit
**User story**
As the operator, I want every write route a player can reach to carry an explicit limit so that no action is left with only the global baseline, now or when new routes are added.

**Acceptance criteria**
- These routes get a per-user limit `RATE_LIMIT_USER_ACTION` (default `60/minute`):
  - `PUT /profile/username`, `PUT /profile/player-id`, `PUT /profile/password`
  - `POST /weekly-summary/{week_id}/reveal`, `POST /weekly-summary/reveal-all`, `POST /weekly-summary/seen`, `POST /weekly-summary/prompted`
  - `POST /claim-events`, `POST /notifications/{notification_id}/dismiss`
  - `DELETE /sessions/{session_id}`, `POST /logout-everywhere`
  - `POST /twitch/merge/confirm`, `POST /twitch/disconnect`, `POST /profile/steam/unlink`
- `POST /simulate/{match_id}` (public, CPU work per call) gets a per-IP limit `RATE_LIMIT_SIMULATE` (default `20/minute`)
- `POST /twitch/mvp` gets a per-IP limit (`RATE_LIMIT_TWITCH_JOIN_IP`)
- A test lists every non-admin `POST`/`PUT`/`PATCH`/`DELETE` route in the app and fails when one has no `@limiter.limit` decorator and is not in a short, commented allowlist (`POST /logout`)
- Admin routes stay on the global baseline: they need admin rights, and destructive ones need a recent re-auth

### Oversized Requests Refused Early
**User story**
As the operator, I want request bodies above a fixed size refused before they are read so that large payloads can't tie up memory or parsing time.

**Acceptance criteria**
- A request whose `Content-Length` is above `MAX_REQUEST_BODY_BYTES` (default `65536`) gets 413 `{"detail": "Request too large"}` without the route running
- A chunked request without `Content-Length` is cut off and refused once its body passes the same size
- Every existing route still works: the app has no file uploads, and the largest JSON bodies (admin player and week forms) are well under 64 KiB
- `GET`, `HEAD` and `OPTIONS` requests are unaffected

### Clear Throttle Responses
**User story**
As a player who clicks too fast, I want a plain message telling me to wait so that I know the site isn't broken.

**Acceptance criteria**
- 429 responses carry `{"detail": "Too many requests. Wait a moment and try again."}` and a `Retry-After` header in seconds
- Draw, booster, reroll and roster actions on the website show that text in their existing status area; the Twitch panel shows its existing neutral message
- Each refused request logs one line at INFO with the route and the key kind (`user`, `ip`, `twitch`), never the IP or the user id, at most once per key and route per minute

### Operator Guidance Against Denial of Service
**User story**
As the operator, I want a short, layered checklist for running Kana Cards behind a proxy so that floods are stopped before they reach the single app process.

**Acceptance criteria**
- `markdown/features/reference/rate-limiting.md` gains a **Layered protection** section covering:
  - the edge, which is the only layer that stops volumetric floods: an optional CDN or WAF such as Cloudflare in front;
  - the reverse proxy: per-IP request rates (`limit_req` in nginx, the `rate_limit` module in Caddy), per-IP connection limits, body size limits, and read and idle timeouts against slow-client attacks;
  - the app: global per-IP, per-user action limits, stricter auth limits, size cap, atomic token spending and cached hot reads (`/twitch/panel`, schedule);
  - host and deployment settings: `APP_BIND_ADDRESS=127.0.0.1`, never `FORWARDED_ALLOW_IPS=*`, a single process
- Example nginx and Caddy snippets with values matching the app's limits
- The section says what the app can't do: absorb bandwidth floods, or share limits across several processes without Redis

## Implementation

### Critical Files
| File | Change |
|---|---|
| `backend/rate_limit.py` | Add `RATE_LIMIT_CARD_ACTION`, `RATE_LIMIT_CARD_ACTION_IP`, `RATE_LIMIT_USER_ACTION`, `RATE_LIMIT_SIMULATE` constants (one place) |
| `backend/routers/cards.py` | Limits on `/draw`, `/draw/booster/{team_id}`, `/roster/{card_id}/reroll` (route wrappers with `request: Request`) |
| `backend/routers/profile.py`, `backend/routers/weekly_summary.py`, `backend/routers/auth.py` | `RATE_LIMIT_USER_ACTION` on the listed routes |
| `backend/twitch_oauth.py`, `backend/steam_openid.py` | `RATE_LIMIT_USER_ACTION` on merge/confirm, disconnect, steam unlink |
| `backend/twitch.py` | Per-IP limit on `POST /twitch/mvp` |
| `backend/routers/leaderboard.py` | `RATE_LIMIT_SIMULATE` on `/simulate/{match_id}` |
| `backend/main.py` | Body-size middleware; 429 handler text, `Retry-After`, throttled log line |
| `frontend/app-cards.js`, `frontend/app-roster.js` | Show the 429 `detail` in the action's status area (confirm existing handling) |
| `.env.example` | New variables |
| `markdown/features/reference/rate-limiting.md`, `markdown/features/reference/commands.md` | Endpoints, configuration, Layered protection section |
| `backend/tests/test_issue_184_action_throttling.py` | New tests |

### Step 1 — Limit constants
Define the four new limits in `backend/rate_limit.py` with `os.getenv(...)` defaults, beside `RATE_LIMIT_GLOBAL`. Existing per-module constants stay where they are.

### Step 2 — Decorate the routes
Follow the existing pattern, a thin `*_route` wrapper taking `request: Request` that calls the plain function, as in `reorder_roster_route` and `get_card_image_route`:
```python
@router.post("/draw")
@limiter.limit(RATE_LIMIT_CARD_ACTION, key_func=key_by_user_or_ip)
@limiter.limit(RATE_LIMIT_CARD_ACTION_IP)
def draw_card_route(request: Request, db=Depends(get_db), current_user: dict = Depends(get_current_user)):
    return draw_card(db, current_user)
```
`key_by_user_or_ip` needs `get_current_user` resolved first (it sets `request.state.session_user_id`), so the dependency stays on the route. Keep direct function calls used by tests unchanged.

### Step 3 — Route coverage test
Walk `app.routes`. For every `APIRoute` with a write method whose path doesn't start with `/admin` (and isn't an admin-guarded route under another prefix such as `/grant-tokens`, `/codes`, `/ingest`, `/recalculate`, `/audit-logs` — detect via a `require_admin` dependency), assert that slowapi has a route-level limit registered (`limiter._route_limits` keyed by the endpoint's qualified name), or that the route is in `ALLOWED_GLOBAL_ONLY = {("POST", "/logout")}` with a comment saying why.

### Step 4 — Body size cap
A small pure-ASGI middleware in `main.py`, before the routers:
- if `Content-Length` is above `MAX_REQUEST_BODY_BYTES`, answer 413;
- otherwise wrap `receive` to count body bytes and answer 413 once the count passes the cap.

Read the cap once at import; an invalid value means `65536`.

### Step 5 — 429 response and log
- **Handler:** change `_rate_limit_handler` to return the plain message and `Retry-After`, from the limit's window: `exc.limit.limit.get_expiry()` or 60.
- **Log line:** emit `logger.info("Rate limited: %s %s (%s)", method, route_path, key_kind)` with a small in-memory "last logged" dict keyed by `(key_hash, route)`. Use the route template, not the raw path.
- **Existing tests:** some assert the old `Rate limit exceeded: …` text. Update them to the new text.

### Step 6 — Frontend
Check that the draw, booster, reroll and roster handlers already show `data.detail` on a non-OK response. Where they show a generic error instead, show `data.detail` for 429 through `setStatus`, which sets `textContent`.

### Step 7 — Docs and env
- **`.env.example`:** add `RATE_LIMIT_CARD_ACTION`, `RATE_LIMIT_CARD_ACTION_IP`, `RATE_LIMIT_USER_ACTION`, `RATE_LIMIT_SIMULATE` and `MAX_REQUEST_BODY_BYTES`.
- **`rate-limiting.md`:** add the new routes to "Endpoints affected", the new variables to Configuration, and the **Layered protection** section with nginx and Caddy snippets.
- **`commands.md`:** add the new variables to the env table.

### Step 8 — Tests
`backend/tests/test_issue_184_action_throttling.py`:
- **Card actions:** the per-user limit gives 429 on the N+1th draw with no token spent; a second user is unaffected; the per-IP limit holds across two accounts.
- **Player actions:** each route in the list has a limit; `/simulate` gives 429 past its limit.
- **Coverage:** the route coverage test from Step 3.
- **Size cap:** 413 for an oversized `Content-Length` and for an oversized chunked body; normal bodies pass; GET is unaffected.
- **429 response:** the body text, `Retry-After`, and a log line holding no IP or user id.

Set small limits through environment variables in the tests, and reset the limiter storage between tests, as the existing rate-limit tests do. Keep `test_issue_85_split_admin_router.py`'s suite-size check in step.

## Verification
- Locally:
  - script 25 `POST /draw` calls from one logged-in session within a minute: the first 20 succeed (tokens permitting) and the rest get 429 with `Retry-After`;
  - a second account still draws.
- `curl -X POST -H 'Content-Length: 100000' …/profile/username` → 413.
- The site works normally when clicking through draws, roster changes, the Weekly Report and profile edits at a human pace.
- The Twitch panel's draws are unaffected (their own `RATE_LIMIT_TWITCH_*` limits).
- `cd backend && python3 -m pytest tests/ -q`.
- On the server, confirm the proxy settings from the Layered protection checklist (bind address, forwarded IPs, proxy rate limits) with the hoster.
