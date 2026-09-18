# Plan: Forgot Password Cooldown

## Context
Issue #122 reported that `POST /forgot-password` had no rate limit at all, allowing unlimited
password-reset emails to be triggered against any known username. Issue #121's rate-limiting
work already closed part of this — `RATE_LIMIT_FORGOT_PASSWORD` (default `3/minute`) — but that
limit is per source *IP*, keyed via `slowapi`'s default `get_remote_address`. It does not stop
an attacker spread across multiple IPs, or one who simply waits a minute between bursts, from
repeatedly hitting the *same account*. Issue #122's own recommendation explicitly asked for
both: "Add a per-username **and** per-IP** cooldown/rate limit" — the per-IP half is done; this
plan adds the remaining per-username half, independent of source IP, following the same pattern
already established for `/login`'s per-username lockout (`backend/routers/auth.py`'s
`_is_locked_out`/`_record_failed_login`/`_clear_failed_logins`, added for issue #121).

The critical constraint, stated directly in the issue and already how this endpoint behaves
today: `/forgot-password` must keep returning `{"status": "ok"}` unconditionally regardless of
whether the username exists, whether an email was actually sent, or whether the account is in
cooldown — anything else re-opens the exact username-enumeration side channel the existing
bcrypt timing-equalization (`_DUMMY_HASH`) already guards against. The cooldown tracker is
keyed by the submitted username string and only ever populated for usernames that resolve to a
real account (the existing fast-exit path for nonexistent usernames is untouched and needs no
new tracking — it already returns the same response, with equalized timing, on every call).
Unlike the login lockout (a *threshold* over a window — a few failed logins are normal), this is
a simple cooldown: at most one password-reset email per account per
`FORGOT_PASSWORD_COOLDOWN_SECONDS` (default `300`, matching `LOGIN_LOCKOUT_WINDOW_SECONDS`'s
default), since a second reset request minutes after the first is inherently suspicious rather
than routine. *Resolves GitHub issue #122.*

## User Stories

### Per-Account Cooldown on Forgot Password
**User story**
As an operator, I want `POST /forgot-password` to allow at most one password-reset email per
account within a cooldown window, independent of source IP, so that an attacker spread across
multiple IPs (or simply patient) can't repeatedly spam a target's inbox once the per-IP limit
resets.

**Acceptance criteria**
- A second `/forgot-password` request for the same username within
  `FORGOT_PASSWORD_COOLDOWN_SECONDS` (default `300`) of the first does not send another email
  or issue another temporary password, even from a different source IP
- The suppressed request still returns `{"status": "ok"}` — identical to both the "username
  doesn't exist" and "email successfully sent" responses, so no new information about account
  existence or cooldown state is exposed by the response body
- The cooldown is keyed by the submitted username string, populated only when the username
  resolves to a real account (the existing nonexistent-username fast-exit path is unchanged)
- The cooldown is configurable via `FORGOT_PASSWORD_COOLDOWN_SECONDS` and is independent of,
  and stacks with, the existing per-IP `RATE_LIMIT_FORGOT_PASSWORD` limit from issue #121 —
  either one suppressing a request is sufficient, neither depends on the other
- A legitimate user who didn't receive the first email (e.g. spam filter, typo'd address they
  then fixed via support) is not permanently blocked — the cooldown expires on its own after
  the configured window, no admin action needed

---

## Implementation

### Critical Files
| File | Change |
|---|---|
| `backend/routers/auth.py` | Add `_forgot_password_in_cooldown()`/`_record_forgot_password_request()` (mirroring the existing `_is_locked_out`/`_record_failed_login` pattern) and wire into `forgot_password()` |
| `.env.example` | Document `FORGOT_PASSWORD_COOLDOWN_SECONDS` |
| `markdown/features/reference/forgot-password-cooldown.md` | New reference doc (stub created by product-planner), cross-referencing `reference/rate-limiting.md` |

No model changes, no migrations — in-memory state only, same reasoning as the existing
per-username login lockout (single-process deployment, no shared-state backend needed).

### Step 1 — Cooldown tracker
Add to `backend/routers/auth.py`, alongside the existing lockout state:
```python
FORGOT_PASSWORD_COOLDOWN_SECONDS = int(os.getenv("FORGOT_PASSWORD_COOLDOWN_SECONDS", "300"))
_last_forgot_password_request: dict[str, float] = {}


def _forgot_password_in_cooldown(username: str) -> bool:
    last = _last_forgot_password_request.get(username)
    return last is not None and (time.time() - last) < FORGOT_PASSWORD_COOLDOWN_SECONDS


def _record_forgot_password_request(username: str):
    _last_forgot_password_request[username] = time.time()
```

### Step 2 — Wire into `forgot_password()`
Insert the cooldown check right after the existing user lookup, before any password/email work
begins — the suppressed path reuses the exact same dummy-hash timing-equalization call and
`{"status": "ok"}` return already used for the nonexistent-username case, so it's
indistinguishable from it in both response body and rough timing:
```python
user = db.query(User).filter(User.username == body.username).first()
if not user or not user.email:
    verify_password("dummy-timing-equalizer", _DUMMY_HASH)
    return {"status": "ok"}

if _forgot_password_in_cooldown(body.username):
    verify_password("dummy-timing-equalizer", _DUMMY_HASH)
    return {"status": "ok"}

_record_forgot_password_request(body.username)
# ...existing temp-password issuance + email send logic, unchanged...
```
Record the cooldown timestamp *before* attempting the email send (not after), so a slow/failing
SMTP send doesn't let a rapid retry bypass the cooldown — matching the existing code's own
`db.rollback()` behavior on email failure, which already leaves the account's temp password
unset; the cooldown timer starting regardless just means a genuinely failed send also has to
wait out the window before retrying, which is an acceptable tradeoff for the abuse protection
this exists for.

### Step 3 — Document the env var
```
# Minimum time between password-reset emails for the same account, independent of source IP.
# Default: 300 (5 minutes). Stacks with RATE_LIMIT_FORGOT_PASSWORD (per-IP, issue #121) —
# either limit suppressing a request is sufficient.
# FORGOT_PASSWORD_COOLDOWN_SECONDS=300
```

### Step 4 — Fill in the feature doc stub
Update `markdown/features/reference/forgot-password-cooldown.md` with final confirmed behavior.

---

## Verification
- `cd backend && python -m pytest tests/ -v` — existing `/forgot-password` tests (enumeration
  safety, timing equalization, TTL) must stay green
- New tests: a second request for the same username within the cooldown window does not call
  `send_email` again and does not overwrite `user.password_hash` a second time, but still
  returns `{"status": "ok"}`; a request for a *different* username during another account's
  cooldown is unaffected; after the cooldown window elapses (mock/advance time), a follow-up
  request for the same username succeeds normally; a cooldown-suppressed response and a
  nonexistent-username response are both exactly `{"status": "ok"}` with no distinguishing
  fields
- Confirm the per-IP (`RATE_LIMIT_FORGOT_PASSWORD`) and per-username cooldown are independent:
  triggering one does not require or depend on the other having also been triggered
