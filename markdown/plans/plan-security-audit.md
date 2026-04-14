# Plan: Security Audit — Eliminate Obvious Vulnerabilities

## Context

A security audit of the FastAPI backend identified several application-level vulnerabilities. The goal is to address the highest-impact, most exploitable issues without over-engineering. Excluded: infrastructure-level concerns (TLS termination, firewall), which belong in deployment config rather than app code.

All findings are in `backend/main.py` unless otherwise noted.

---

## Issues by Priority

### P1 — Broken Access Control

#### 1. `/cards/{card_id}/image` — no authentication, no ownership check
Any unauthenticated request with an arbitrary `card_id` generates and returns a full card image. No login required, no check that the card belongs to the caller. This wastes server resources (PIL compositing + HTTP image fetches) and leaks card data.

**Fix:** Add `current_user = Depends(get_current_user)` to the endpoint. No ownership check needed beyond authentication — card images are not sensitive enough to restrict per-user.

#### 2. `/roster/{user_id}` and `/profile/{user_id}` — unauthenticated read
Both endpoints expose user data (roster, season points, card modifiers, linked player) to completely unauthenticated callers. Any crawler can enumerate all users' rosters by iterating `user_id`.

In a fantasy league, viewing other users' rosters is likely intentional (competitive transparency), so cross-user reads can stay — but the caller must be authenticated.

**Fix:** Add `_: dict = Depends(get_current_user)` to both endpoints (auth required, no ownership restriction).

---

### P2 — Brute-Force / Rate Limiting

#### 3. No rate limiting on `/login`, `/register`, `/forgot-password`
`/login` has no throttling at all — unlimited password guessing attempts. `/forgot-password` has no limit, enabling email spam to arbitrary accounts. `/register` has no limit, enabling account farming.

**Fix:** Add `slowapi` (the standard FastAPI rate-limiting library) to `backend/requirements.txt`. Wire it up as a FastAPI middleware and apply per-IP limits:

| Endpoint | Limit |
|---|---|
| `POST /login` | 10 / minute |
| `POST /register` | 5 / hour |
| `POST /forgot-password` | 3 / hour |

`slowapi` uses an in-memory store by default (no Redis required). Rate-limit exceeded returns HTTP 429.

```python
# backend/main.py — additions
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

@app.post("/login")
@limiter.limit("10/minute")
def login(request: Request, ...):
    ...
```

---

### P3 — Input Validation Gaps

#### 4. No username or password length validation at registration
`RegisterBody` has bare `str` fields — a user can register with a 1-character username or a 1-character password. `change_password` validates `>= 6 chars` but `register` validates nothing. Promo codes similarly have no max length.

**Fix:** Use Pydantic `Field()` constraints on the relevant `BaseModel` classes:

```python
from pydantic import Field

class RegisterBody(BaseModel):
    username: str = Field(min_length=2, max_length=50)
    email: str
    password: str = Field(min_length=8, max_length=128)

class UpdateUsernameBody(BaseModel):
    username: str = Field(min_length=2, max_length=50)

class CreateCodeBody(BaseModel):
    code: str = Field(min_length=1, max_length=50)
    token_amount: int
```

Also align `change_password` minimum from 6 → 8 chars to match registration.

---

### P4 — Session Cookie HTTPS Flag

#### 5. `https_only=False` is hardcoded
Session cookies are always sent over HTTP even if the app is behind HTTPS. The flag should follow the deployment environment, not be hardcoded.

**Fix:** Read from env var so local dev stays on HTTP and production enforces HTTPS:

```python
_https_only = os.getenv("HTTPS_ONLY", "false").lower() == "true"
app.add_middleware(
    SessionMiddleware,
    secret_key=_secret_key,
    same_site="lax",
    https_only=_https_only,
)
```

Add `HTTPS_ONLY=true` to the production `.env` / docker-compose environment block.

---

## Critical Files

| File | Change |
|---|---|
| `backend/main.py` | Auth on image/roster/profile endpoints; rate-limit decorators + middleware; `https_only` env var; Pydantic Field constraints |
| `backend/requirements.txt` | Add `slowapi` |
| `docker-compose.yml` | Add `HTTPS_ONLY` env var (prod) |

---

## Execution Order

1. `requirements.txt` — add `slowapi`
2. `main.py` — Pydantic `Field()` constraints (zero risk, purely additive)
3. `main.py` — add auth (`Depends(get_current_user)`) to image/roster/profile endpoints
4. `main.py` — wire `slowapi` limiter + apply `@limiter.limit()` decorators
5. `main.py` — `https_only` env var
6. `docker-compose.yml` — expose `HTTPS_ONLY` variable

---

## Verification

- Register with a 1-character username → expect 422
- Register with a 7-character password → expect 422
- `GET /roster/1` without a session cookie → expect 401
- `GET /cards/1/image` without a session cookie → expect 401
- POST `/login` 11 times in one minute → expect 429 on the 11th
- Set `HTTPS_ONLY=true` and check that session cookies have the `Secure` attribute in response headers
- `docker compose -f docker-compose.yml -f docker-compose.dev.yml up --build` — confirm app starts and all existing flows (login, draw, roster view) still work
