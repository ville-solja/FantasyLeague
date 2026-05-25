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
