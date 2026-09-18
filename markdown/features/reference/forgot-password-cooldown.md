# Forgot Password Cooldown

Per-account cooldown on `POST /forgot-password`, independent of source IP, closing the
remaining part of a reported inbox-spam vector after issue #121 already added a per-IP limit.

*(see `markdown/plans/plan-issue-122-forgot-password-cooldown.md`, resolves GitHub issue #122)*

---

## Relationship to issue #121's rate limiting

See `reference/rate-limiting.md` first — `RATE_LIMIT_FORGOT_PASSWORD` (per-IP, default
`3/minute`) already covers rapid-fire abuse from a single source. This feature adds the
remaining, narrower gap: an attacker spread across multiple IPs, or simply waiting out the
per-IP window, could still repeatedly trigger reset emails against one specific account. The
two limits are independent and stack — either one suppressing a request is sufficient.

## Approach

`POST /forgot-password` (`backend/routers/auth.py`) tracks the last successful reset-email
trigger per username, in an in-memory `_last_forgot_password_request: dict[str, float]` module
global keyed by the submitted username string — mirroring the per-username login lockout added
for issue #121 (`_is_locked_out`/`_record_failed_login`), and the same reasoning applies:
single-process deployment, no shared-state backend needed, state resetting on restart is an
acceptable tradeoff.

`_forgot_password_in_cooldown(username)` / `_record_forgot_password_request(username)` implement
the check and the write. The check runs right after the existing user lookup, before any
password/email work:

- Nonexistent username or no email on file → existing fast-exit (`verify_password` against
  `_DUMMY_HASH`, then `{"status": "ok"}`) — unchanged by this feature.
- Existing username, but a prior request for it is still within
  `FORGOT_PASSWORD_COOLDOWN_SECONDS` → the *same* fast-exit call and `{"status": "ok"}` response
  as the nonexistent-username case, so a cooldown-suppressed request is indistinguishable from
  one against an unknown username, both in response body and in rough timing. No email is sent
  and no reset token is issued.
- Otherwise → `_record_forgot_password_request(username)` is called **before** the reset-token
  issuance and `send_email` call (not after), so a slow or failing SMTP send can't be exploited
  via rapid retry to bypass the cooldown. The token issuance + email logic then proceeds
  unchanged (see `reference/password-reset-token-flow.md` for what that now does — issue #123
  replaced the original temp-password issuance this cooldown was originally written against).

The cooldown is only ever recorded for usernames that resolve to a real account — the existing
nonexistent-username fast-exit path is untouched and never populates the tracker.

## Configuration

| Variable | Default | Description |
|---|---|---|
| `FORGOT_PASSWORD_COOLDOWN_SECONDS` | `300` | Minimum time between password-reset emails for the same account, independent of source IP |

## Tests

`backend/tests/test_issue_122_forgot_password_cooldown.py` covers: suppression of a second
request for the same username within the window (including from a different source IP);
the suppressed response body/status matching the nonexistent-username response exactly; the
nonexistent-username path never populating the cooldown tracker; per-username scoping (one
account's cooldown does not affect another's); the env var controlling the window length;
independence from/stacking with the per-IP `RATE_LIMIT_FORGOT_PASSWORD` limit; and expiry of
the cooldown after the window elapses (including a boundary case just before expiry).
