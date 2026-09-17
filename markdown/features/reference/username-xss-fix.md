# Username XSS Fix

Fixes a stored-XSS privilege-escalation vulnerability: a username containing HTML markup could
execute arbitrary JavaScript in an admin's session the moment they viewed a page listing it —
including calling real admin functions like `toggleAdmin(id)`.

*(see `markdown/plans/plan-issue-115-username-xss-fix.md`, resolves GitHub issue #115)*

---

## The vulnerability

`RegisterBody.username` (`backend/routers/auth.py`) only enforces `min_length`/`max_length` — no
character restriction — so any self-registered account can set its username to arbitrary HTML.
Three frontend surfaces rendered `username`/`actor_username` by concatenating it directly into an
`innerHTML` string with no escaping:

- `frontend/app-admin-users.js::_renderUsers` (User Management table)
- `frontend/app-admin-ingest.js` (Audit Log's `actor_username`)
- `frontend/app-admin-demo.js` (seeded demo-account usernames)

A username like `<img src=x onerror="toggleAdmin(69)">` renders as a broken image tag; the
browser's `onerror` handler then fires with the *viewing admin's own authenticated session*,
silently calling `toggleAdmin(69)` — toggling admin status for whichever user id the attacker
chose, every time any admin opened one of those pages. This is exactly what GitHub issue #115
reported as a user being "promoted/demoted constantly."

`frontend/app-leaderboard.js` already escapes usernames correctly via `_escHtml()`
(`frontend/app-globals.js`) — the admin surfaces above were simply missed.

## Fix

1. **Display-side (the actual fix):** wrap `username`/`actor_username` in `_escHtml()` at all
   three sites above — same helper, same pattern already used on the leaderboard.
   - `frontend/app-admin-users.js::_renderUsers` — `<td>${_escHtml(u.username)}${testerBadge}${adminBadge}</td>`
   - `frontend/app-admin-ingest.js` audit log row — `<td>${r.actor_username ? _escHtml(r.actor_username) : "<em style='color:#555'>system</em>"}</td>`
   - `frontend/app-admin-demo.js` seeded accounts row — `<td>${_escHtml(a.username)}</td><td style="font-family:monospace;">${_escHtml(a.password)}</td>`
2. **Registration-side (defense in depth):** `RegisterBody.username`
   (`backend/routers/auth.py`) and `UpdateUsernameBody.username`
   (`backend/routers/profile.py`, backing `PUT /profile/username`) both gained a
   `@field_validator("username")` that raises `ValueError` (surfaced by FastAPI as HTTP 422) if
   the value contains any of `<`, `>`, `"`, `'`. Does not retroactively rename any already-stored
   username — the display-side fix is what protects against those, confirmed by
   `test_existing_legacy_html_username_unaffected_by_new_validation`.

Covered by `backend/tests/test_issue_115_username_xss_fix.py` (12 tests: 6 static file-content
assertions for the three escaping sites, 6 endpoint tests via `TestClient` for the registration/
profile validators).

## Operational follow-up (not code)

Any account with a username already containing these characters should be found and
renamed/disabled by hand, and any user id the exploit may have targeted (via `toggleAdmin`)
should have its actual `is_admin` value manually re-verified — it may already have been
incorrectly toggled before this fix shipped.
