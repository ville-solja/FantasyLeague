# Plan: Rate Limiting

## Context
A community security disclosure (2026-09-18) found that no endpoint in the app enforces any
rate limit — `POST /login` in particular can be brute-forced with no lockout, delay, or
CAPTCHA; bcrypt hashing slows guessing but does not meaningfully stop a sustained attack. This
plan adds a global per-IP baseline across every route plus stricter per-IP limits on the three
most sensitive auth endpoints (`/login`, `/register`, `/forgot-password`), and a per-username
failed-login lockout on `/login` independent of source IP. The app runs as a single uvicorn
process with no `--workers` flag (confirmed in `backend/Dockerfile`), so an in-memory limiter is
sufficient — no Redis or other shared-state backend is needed. `slowapi` (a thin FastAPI/Starlette
wrapper around the `limits` library) is the natural fit: it's a single new dependency, supports
in-memory storage out of the box, and integrates via a decorator on individual routes plus one
app-wide middleware for the baseline.

Two related, narrower reports from the same disclosure batch are explicitly **out of scope**
here and tracked separately: GitHub issue #122 (per-account cooldown on `/forgot-password`
regardless of IP, to stop inbox-spam) and issue #123 (the endpoint overwriting the real password
before verifying email ownership). This plan only adds IP-based rate limiting to
`/forgot-password`, consistent with the other two endpoints — it does not change that endpoint's
account-level behavior. *Resolves GitHub issue #121.*

## User Stories

### Global Rate Limiting Baseline
**User story**
As an operator, I want every endpoint to enforce a baseline request-rate limit so that no
single client can flood the app with requests regardless of which endpoint they target.

**Acceptance criteria**
- A default per-IP rate limit applies globally to every route via a single middleware
  registration, not per-endpoint opt-in
- Exceeding the limit returns HTTP 429 with a `{"detail": "..."}` body matching the app's
  existing error response shape (not slowapi's default `{"error": "..."}` shape)
- The limit is configurable via `RATE_LIMIT_GLOBAL` (default `200/minute`) so operators can
  tune it without a code change
- The default is generous enough that Docker's own healthcheck (`GET /health` every 30s) and
  normal frontend polling are never blocked by legitimate traffic

### Brute-Force Protection on Login
**User story**
As a security-conscious operator, I want `POST /login` to reject excessive attempts so that
an attacker cannot brute-force a password by sending unlimited login requests.

**Acceptance criteria**
- `POST /login` enforces a stricter per-IP limit than the global baseline, configurable via
  `RATE_LIMIT_LOGIN` (default `5/minute`)
- Independently of IP, repeated failed login attempts against the same username within a
  rolling window trigger a temporary per-username lockout, configurable via
  `LOGIN_LOCKOUT_THRESHOLD` (default `10` attempts) and `LOGIN_LOCKOUT_WINDOW_SECONDS`
  (default `300`) — this catches an attacker rotating source IPs against one account, which
  the per-IP limit alone would not
- A successful login for a username resets that username's failed-attempt counter
- Exceeding either limit returns a generic rate-limit message that does not reveal whether
  the submitted username exists (this preserves the existing username-enumeration protection
  pattern already used by `/forgot-password`'s timing-equalization)

### Rate Limiting on Registration
**User story**
As an operator, I want `POST /register` to enforce a stricter per-IP limit than the baseline
so the endpoint can't be used to mass-create accounts or probe for taken usernames/emails via
its 409 conflict response.

**Acceptance criteria**
- `POST /register` enforces a per-IP limit configurable via `RATE_LIMIT_REGISTER` (default
  `5/minute`), stricter than the global baseline
- Exceeding the limit returns 429 with the same `{"detail": "..."}` shape as other
  rate-limited responses

### Rate Limiting on Forgot Password
**User story**
As an operator, I want `POST /forgot-password` to enforce a stricter per-IP limit so the
endpoint's existing username-enumeration-safe design isn't undermined by unlimited automated
requests from one source.

**Acceptance criteria**
- `POST /forgot-password` enforces a per-IP limit configurable via
  `RATE_LIMIT_FORGOT_PASSWORD` (default `3/minute`), stricter than the global baseline
- The endpoint's existing behavior (always returning `{"status": "ok"}` regardless of whether
  the username exists, and the bcrypt timing-equalization on the fast-exit path) is unchanged
- Per-account cooldown independent of source IP, and the password-overwrite-before-verification
  issue, are explicitly out of scope for this plan — see GitHub issues #122 and #123

---

## Implementation

### Critical Files
| File | Change |
|---|---|
| `backend/requirements.txt` | Add `slowapi` dependency |
| `backend/main.py` | Create the shared `Limiter` instance, register `SlowAPIMiddleware` and a custom 429 exception handler matching `{"detail": ...}` |
| `backend/routers/auth.py` | Add `@limiter.limit(...)` decorators to `login`, `register`, `forgot_password`; add `request: Request` param to `forgot_password` (the other two already accept it); add the per-username failed-login lockout to `login` |
| `.env.example` | Document `RATE_LIMIT_GLOBAL`, `RATE_LIMIT_LOGIN`, `RATE_LIMIT_REGISTER`, `RATE_LIMIT_FORGOT_PASSWORD`, `LOGIN_LOCKOUT_THRESHOLD`, `LOGIN_LOCKOUT_WINDOW_SECONDS` |
| `markdown/features/reference/rate-limiting.md` | New reference doc (stub created by product-planner) |

No model changes, no migrations — the per-username lockout state is in-memory only (same
reasoning as the in-memory global limiter: single-process deployment, no shared-state backend
needed, and lockout state resetting on restart is an acceptable tradeoff for this app's scale).

### Step 1 — Add the dependency
Append to `backend/requirements.txt`:
```
slowapi>=0.1.9,<0.2
```

### Step 2 — Create the shared limiter and wire it into `main.py`
```python
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.middleware import SlowAPIMiddleware
from slowapi.errors import RateLimitExceeded

_RATE_LIMIT_GLOBAL = os.getenv("RATE_LIMIT_GLOBAL", "200/minute")

limiter = Limiter(key_func=get_remote_address, default_limits=[_RATE_LIMIT_GLOBAL])
app.state.limiter = limiter
app.add_middleware(SlowAPIMiddleware)


@app.exception_handler(RateLimitExceeded)
async def _rate_limit_handler(request: Request, exc: RateLimitExceeded):
    return JSONResponse(status_code=429, content={"detail": f"Rate limit exceeded: {exc.detail}"})
```
Register this after `SessionMiddleware`/`SecurityHeadersMiddleware`/`CORSMiddleware`, before
the router includes. `limiter` needs to be importable from `routers/auth.py` — either export it
from `main.py` and import back (watch for circular imports, since `main.py` already imports the
routers) or define `limiter` in a small shared module (e.g. `backend/rate_limit.py`) that both
`main.py` and `routers/auth.py` import from — the latter avoids the circular-import risk and
matches this codebase's existing pattern of small shared modules (`clock.py`, `card_utils.py`).

### Step 3 — Apply stricter per-IP limits to the three routes
In `backend/routers/auth.py`:
```python
from rate_limit import limiter

RATE_LIMIT_LOGIN = os.getenv("RATE_LIMIT_LOGIN", "5/minute")
RATE_LIMIT_REGISTER = os.getenv("RATE_LIMIT_REGISTER", "5/minute")
RATE_LIMIT_FORGOT_PASSWORD = os.getenv("RATE_LIMIT_FORGOT_PASSWORD", "3/minute")


@router.post("/login")
@limiter.limit(RATE_LIMIT_LOGIN)
def login(request: Request, body: LoginBody, db=Depends(get_db)):
    ...


@router.post("/register")
@limiter.limit(RATE_LIMIT_REGISTER)
def register(request: Request, body: RegisterBody, db=Depends(get_db)):
    ...


@router.post("/forgot-password")
@limiter.limit(RATE_LIMIT_FORGOT_PASSWORD)
def forgot_password(request: Request, body: ForgotPasswordBody, db=Depends(get_db)):
    ...
```
`forgot_password` currently has no `request: Request` parameter — slowapi's decorator requires
it to resolve the client's address, so this is a required signature change, not optional.

### Step 4 — Per-username failed-login lockout
This is independent of slowapi's per-IP decorator (which can't key on request-body fields
without extra plumbing) — a small dedicated in-memory tracker inside `auth.py` is simpler and
matches the existing `_DUMMY_HASH`-style module-level state already used for the
timing-equalization fix:
```python
from collections import defaultdict

_LOGIN_LOCKOUT_THRESHOLD = int(os.getenv("LOGIN_LOCKOUT_THRESHOLD", "10"))
_LOGIN_LOCKOUT_WINDOW_SECONDS = int(os.getenv("LOGIN_LOCKOUT_WINDOW_SECONDS", "300"))
_failed_login_attempts: dict[str, list[float]] = defaultdict(list)


def _is_locked_out(username: str) -> bool:
    now = time.time()
    attempts = _failed_login_attempts[username]
    attempts[:] = [t for t in attempts if now - t < _LOGIN_LOCKOUT_WINDOW_SECONDS]
    return len(attempts) >= _LOGIN_LOCKOUT_THRESHOLD


def _record_failed_login(username: str):
    _failed_login_attempts[username].append(time.time())


def _clear_failed_logins(username: str):
    _failed_login_attempts.pop(username, None)
```
Wire into `login()`: check `_is_locked_out(body.username)` first (return 429 with a generic
message before touching the DB or bcrypt at all, same fast-exit spirit as the existing
timing-equalization on `/forgot-password`), call `_record_failed_login` on the existing
`401 Invalid username or password` path, and `_clear_failed_logins` right after a successful
login's `request.session[...]` assignment.

### Step 5 — Fill in the feature doc stub
Update `markdown/features/reference/rate-limiting.md` with the final limiter values, the env
var table, and the exception-handler response shape, once implemented.

---

## Verification
- `cd backend && python -m pytest tests/ -v` — existing suite must stay green; the login/
  register/forgot-password tests will need `request` fixtures if any call the router functions
  directly rather than through `TestClient` (check `backend/tests/test_issue_115_username_xss_fix.py`
  and any other test importing these functions directly, since `@limiter.limit` wraps the
  function and needs a real `Request` object, not a bare mock, when called directly rather than
  through FastAPI's dependency injection)
- New tests: hammer `POST /login` past `RATE_LIMIT_LOGIN` from one `TestClient` and assert a
  429 with `{"detail": "..."}`; hammer failed logins against one username past
  `LOGIN_LOCKOUT_THRESHOLD` from *varying* `X-Forwarded-For`/client addresses if feasible, and
  assert lockout still triggers; assert a successful login clears a prior partial lockout
  count; repeat the 429-on-exceed check for `/register` and `/forgot-password`
- Manually verify `docker compose up` still passes its healthcheck (30s interval, well under
  any reasonable `RATE_LIMIT_GLOBAL`)
- Confirm `/forgot-password`'s existing behavior (always `{"status": "ok"}`, bcrypt timing
  equalization) is unchanged by running its existing test coverage
