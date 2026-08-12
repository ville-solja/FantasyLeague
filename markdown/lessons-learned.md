# Lessons Learned

Persistent notes written by agents during their runs. Read this before starting work.
Append new entries when you encounter a novel problem not already documented here.

Entries are sorted newest-first. Entries are append-only — do not rewrite or delete existing entries.

Format:

---

### YYYY-MM-DD — [agent-name] — [category]
**Problem:** One-sentence description of the pitfall or recurring issue.
**Solution:** What to do instead, or the correct approach.

---

### 2026-08-12 — security-patcher — testing
**Problem:** `py/redos` (CWE-1333/400/730) flagged `r'<thead><tr>(<th>.*?</th>)+</tr></thead>...'`
in `backend/tests/test_mvp_visibility.py`. The inner `.*?` (non-greedy, `re.S` so it also
matches newlines) inside a `+`-repeated group is the classic ambiguous-repetition ReDoS shape:
`.*?` can match across a `</th>` boundary into the next `<th>`, so the regex engine has multiple
ways to partition the same input across repetitions of the group, causing exponential
backtracking on crafted input. Low real-world risk here (the match target is a static,
developer-controlled `frontend/index.html`, not user input), but the pattern itself is the
security-relevant thing CodeQL flags, and the same shape could reappear in a genuinely
user-facing regex later.
**Solution:** Replace the ambiguous `.*?` with a negated character class scoped to what the
content actually needs — `[^<]*` — since real `<th>` cells here contain only plain text, never
nested tags. `[^<]*` can never match the `<` that starts `</th>`, removing the overlap between
repetitions entirely and eliminating the backtracking blowup while matching the exact same
strings as before. General pattern: for `(TAG_OPEN.*?TAG_CLOSE)+`-style regexes over HTML/XML-ish
text, prefer a negated-class exclusion of the tag-opening character over `.*?` whenever the
content is known not to contain nested tags.

---

### 2026-08-11 — security-patcher — endpoints
**Problem:** `py/stack-trace-exposure` (CWE-209) flagged `result["error"] = str(e)` in the
admin-only `GET /admin/schedule/debug` diagnostic endpoint (`backend/routers/admin_ingest.py`).
The endpoint's entire purpose is surfacing why `SCHEDULE_SHEET_URL` fetches fail, so returning
nothing useful would defeat it — but CodeQL's taint tracker doesn't model `Depends(require_admin)`
as a sanitizer, so raw exception-message flow to any HTTP response is flagged regardless of auth.
**Solution:** Log the full exception server-side via `logger.exception(...)` (this repo's
established `logging.getLogger(__name__)` pattern, e.g. `backend/routers/auth.py`'s forgot-password
handler), and return only `type(e).__name__` (e.g. `"ConnectionError"`, `"Timeout"`) to the caller
instead of `str(e)`. This keeps the endpoint diagnostically useful (failure category is visible)
without leaking exception message text, which breaks CodeQL's taint flow since the exception class
name is a different derivation than the message content the query tracks.

---

### 2026-08-03 — developer — testing
**Problem:** `test_issue_85_split_admin_router.py::test_full_suite_pass_skip_counts_match_pre_split_baseline` hardcodes an exact `"448 passed"` string from a subprocess run of the whole suite ("as of this writing") — it breaks the instant any other plan adds new passing tests anywhere, even in unrelated files, which is the normal/expected outcome of this repo's plan-driven workflow.
**Solution:** When a change legitimately adds N new passing tests, bump that hardcoded count (and the mirrored docstring number) by N rather than treating the failure as a regression in the new work — but only after confirming via `git stash` that the rest of the suite (`--ignore` both that file and the new test file) still matches the pre-change baseline exactly.

---

### 2026-08-03 — developer — models
**Problem:** For raw `sqlalchemy.text()` queries with a dynamic `WHERE col IN (...)` list (used throughout `backend/schedule.py`, which has no ORM model imports), `text("... IN :ids")` alone does not expand a Python list into `(?, ?, ?)` placeholders.
**Solution:** Chain `.bindparams(bindparam("ids", expanding=True))` onto the `text(...)` statement, e.g. `text("SELECT ... WHERE match_id IN :ids").bindparams(bindparam("ids", expanding=True))`, then pass `{"ids": match_ids}` to `execute()`.

---

### 2026-07-22 — security-patcher — frontend
**Problem:** CodeQL `js/request-forgery` fires when a value from `e.dataTransfer.getData()` is interpolated directly into a fetch URL path segment, even when the base URL is fixed and the ID was originally an integer.
**Solution:** Parse with `parseInt(val, 10)` and guard with `Number.isFinite()` before interpolating into the URL — integers cannot contain path-traversal characters, which both eliminates the actual risk and breaks the taint chain.

---

### 2026-05-25 — security-reviewer — endpoints
**Problem:** `POST /forgot-password` returns immediately for unknown usernames but runs bcrypt + SMTP (1-3s) for valid ones — a timing side channel that reveals whether a username exists.
**Solution:** Call `verify_password("dummy", _DUMMY_HASH)` on the fast-exit path to equalise bcrypt latency. Store `_DUMMY_HASH = hash_password("dummy-timing-equalizer")` at module load time (runs once, not per request).

---

### 2026-05-25 — developer — testing
**Problem:** Helper functions defined inside `routers/cards.py` cannot be imported in `backend/tests/` because importing the router module triggers `from fastapi import ...`, which fails when FastAPI is not installed locally.
**Solution:** Extract pure-logic helpers (like `_roll_rarity` and `_pick_player`) into a separate `backend/card_draw.py` module that only imports from `models` and stdlib. The router then imports from `card_draw`, and tests import from `card_draw` directly without triggering the FastAPI dependency.

---

### 2026-05-25 — developer — testing
**Problem:** `seed_admin_from_env()` uses `SessionLocal()` internally, so the `db` fixture cannot inject the in-memory test DB directly.
**Solution:** Patch `seed.SessionLocal` via `monkeypatch.setattr` to return the in-memory session before calling the function under test.

---

### 2026-05-25 — agent-steward — endpoints
**Problem:** `get_current_user` and `require_admin` auth dependencies are not defined in `backend/main.py` or `backend/auth.py`.
**Solution:** Read `backend/deps.py` — that is where both dependencies are defined.

---

### 2026-05-25 — agent-steward — endpoints
**Problem:** Almost all FastAPI endpoints are in `backend/routers/*.py`, not `backend/main.py`; reading only `main.py` misses all endpoint definitions.
**Solution:** Read every file under `backend/routers/` to get the full endpoint list.

---

### 2026-05-25 — agent-steward — file-paths
**Problem:** `frontend/app.js` no longer exists; the frontend is split into `frontend/app-*.js` modules, one per tab.
**Solution:** Reference the correct module files: `frontend/app-globals.js`, `frontend/app-init.js`, `frontend/app-auth.js`, `frontend/app-cards.js`, `frontend/app-admin.js`, `frontend/app-roster.js`, `frontend/app-leaderboard.js`, `frontend/app-players.js`, `frontend/app-profile.js`.

---
