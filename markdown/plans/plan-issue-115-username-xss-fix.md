# Plan: Username XSS Fix

## Context
Issue #115 reports user "Eul" being repeatedly promoted/demoted with no admin action taken —
the attached screenshot shows why: a stored username of
`<img src=x alt="Eul" onerror="toggleAdmin(69)">`. This is a **live, actively-exploitable
stored-XSS privilege-escalation vulnerability**, not a display glitch. `RegisterBody.username`
(`backend/routers/auth.py`) only enforces `min_length`/`max_length` — no character/format
restriction — so any self-registered account can set its username to arbitrary HTML. Confirmed
in code: `frontend/app-admin-users.js::_renderUsers` interpolates `u.username` directly into an
`innerHTML` string with no escaping. Every time an admin opens User Management, the browser
attempts to load the fake `<img src=x>`, fails, and its `onerror` fires — calling the real
global `toggleAdmin(69)` function with the *admin's own authenticated session*, silently
toggling admin status for whichever user id the attacker chose. This is how a malicious username
can grant an attacker-controlled account admin rights just by getting any admin to view that one
page — matching exactly what was reported.

Two more instances of the same unescaped pattern were found while investigating, both real
attack surfaces since both fields are populated from user-controlled/user-triggered data:
`frontend/app-admin-ingest.js` (Audit Log's `actor_username`, logged on ordinary actions like
registration) and `frontend/app-admin-demo.js` (seeded demo account usernames — lower risk since
those are system-generated, fixed for consistency). This repo already has the correct pattern in
active use — `frontend/app-leaderboard.js` calls `_escHtml(r.username)` (helper defined in
`frontend/app-globals.js`) — the admin surfaces were simply missed.

**This is a security incident, not a routine bug — recommend an immediate targeted fix ahead of
the normal planning-to-review cycle**, in addition to this plan's formal record. Any account
currently or recently matching this pattern should also have its actual current `is_admin`
status manually verified, since it may already have been toggled to `true` by this exploit.

*Resolves GitHub issue #115.*

## User Stories

### Usernames Cannot Execute Script in Admin Views
**User story**
As an admin, I want usernames to always render as plain text in every admin panel view, so a
malicious username can never execute JavaScript in my session or change another account's
privileges without my explicit action.

**Acceptance criteria**
- `frontend/app-admin-users.js::_renderUsers` HTML-escapes `u.username` before it's concatenated
  into the users table's `innerHTML`, using the same `_escHtml()` helper already used correctly
  in `frontend/app-leaderboard.js`
- `frontend/app-admin-ingest.js`'s Audit Log rendering escapes `r.actor_username` the same way
- `frontend/app-admin-demo.js`'s seeded-accounts display escapes `a.username` the same way
- A username containing HTML/script markup (e.g. an `<img onerror=...>` payload) renders as
  inert plain text in all three views — no request fires, no DOM element with a broken `src` is
  created, and no admin action (promote/demote, token grant, etc.) is ever triggered by simply
  viewing a page
- No change to how usernames are stored, validated at registration, or displayed anywhere that
  already escapes correctly (e.g. the leaderboard) — this only closes the three missed spots

---

### Reject Usernames Containing HTML-Significant Characters at Registration
**User story**
As an operator, I want the registration and username-change endpoints to reject usernames
containing characters that have no legitimate use in a display name, so this class of payload
can't be stored in the first place — defense in depth alongside the display-side fix.

**Acceptance criteria**
- `POST /register` and `PUT /profile/username` (or wherever username changes are accepted)
  reject a username containing `<`, `>`, `"`, or `'` with a clear 422 error, in addition to the
  existing length constraint
- This is a second, independent layer — the display-side escaping fix above is the actual fix
  for any username already stored before this validation existed, and must not be treated as
  optional just because this validation also landed
- Existing valid usernames (already stored) are unaffected — this only constrains new
  registrations/renames going forward, no retroactive rename of existing accounts

---

## Implementation

### Critical Files
| File | Change |
|---|---|
| `frontend/app-admin-users.js` | Wrap `u.username` in `_escHtml()` in `_renderUsers` |
| `frontend/app-admin-ingest.js` | Wrap `r.actor_username` in `_escHtml()` in the audit log row renderer |
| `frontend/app-admin-demo.js` | Wrap `a.username` in `_escHtml()` in the seeded-accounts row renderer |
| `backend/routers/auth.py` | Add a character-class validator to `RegisterBody.username` (and the profile username-change body, if it lives elsewhere) rejecting `<`, `>`, `"`, `'` |

### Step 1 — Escape the three rendering sites (the actual fix)
`_escHtml()` already exists in `frontend/app-globals.js` and is loaded on every admin page (it's
already used by `app-leaderboard.js`), so no new helper or script tag is needed — just wrap the
three interpolations:
```js
// app-admin-users.js, _renderUsers
<td>${_escHtml(u.username)}${testerBadge}${adminBadge}</td>
```
```js
// app-admin-ingest.js, audit log row
<td>${r.actor_username ? _escHtml(r.actor_username) : "<em style='color:#555'>system</em>"}</td>
```
```js
// app-admin-demo.js, seeded accounts row
tr.innerHTML = `<td>${_escHtml(a.username)}</td><td style="font-family:monospace;">${_escHtml(a.password)}</td>`;
```

### Step 2 — Registration-time validation (defense in depth)
In `backend/routers/auth.py`, add a Pydantic validator to `RegisterBody.username` (and wherever
a username can be *changed* post-registration) rejecting `<`, `>`, `"`, `'`:
```python
from pydantic import field_validator

class RegisterBody(BaseModel):
    username: str = Field(min_length=1, max_length=64)

    @field_validator("username")
    @classmethod
    def no_html_significant_chars(cls, v: str) -> str:
        if any(c in v for c in '<>"\''):
            raise ValueError("Username cannot contain < > \" '")
        return v
```
Apply the same validator to the profile username-change body if it's a separate Pydantic model.

### Step 3 — Immediate operational follow-up (not code — do this regardless of when the fix ships)
- Manually inspect the `users` table for any username containing `<`, `>`, `"`, or `'` and
  rename/disable those accounts
- Manually verify user id 69's (and any other affected id's) actual current `is_admin` value —
  it may already have been toggled `true` by this exploit and needs to be corrected by hand
- Check the audit log for unexpected `admin_toggle`-type entries around when this was first
  reported, to see how many times the toggle actually fired and who was affected

## Verification
- Seed a test user with `username = '<img src=x onerror="alert(1)">'`, load Admin → User
  Management, Audit Log, and (with `DEMO_MODE=true`) the seeded-demo-accounts view — confirm the
  literal text renders in each, no dialog/request/side effect fires
- Confirm `_escHtml()` output for that username still lets a real admin identify/manage the
  account (it's still selectable, promotable, etc. — only the *rendering* changed)
- Attempt `POST /register` with a username containing `<`/`>`/`"`/`'` — confirm 422
- Confirm a normal username (letters, digits, common punctuation not in the rejected set) is
  unaffected by either change
- Run `cd backend && python -m pytest tests/ -v` — full suite passes
