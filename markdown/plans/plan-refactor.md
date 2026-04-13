# Plan: Codebase Refactoring

## Context

A broad architectural review identified structural issues, dead code, and duplicated patterns accumulated across the codebase. No single item is catastrophic, but together they make the code harder to maintain and introduce latent bugs (session leaks, silent failures). This plan addresses the highest-impact items in order of risk, keeping scope practical.

The frontend is excluded — it is vanilla JS/HTML and a rewrite would be a separate project.

---

## Issues by Priority

### P1 — Correctness / Safety

#### 1. DB session leaks (no try/finally)
**Affected files:** All 46 endpoints in `backend/main.py`, `backend/enrich.py`

Every endpoint does `db = SessionLocal()` ... `db.close()`. If an unhandled exception occurs between open and close, the session is never returned. The fix is a single FastAPI dependency used by all endpoints:

```python
# backend/database.py — add alongside existing SessionLocal
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
```

Each endpoint then becomes:
```python
@app.get("/some-endpoint")
def handler(db = Depends(get_db)):
    ...  # no manual open/close
```

This is the most impactful single change. Eliminates all ~46 manual `db = SessionLocal()` / `db.close()` pairs and guarantees cleanup. Existing early-close calls (`if not user: db.close(); raise HTTPException`) must be removed — the finally block handles it.

#### 2. Background threads missing try/finally on sessions
**File:** `backend/main.py` — `_week_maintenance_loop()`, `_run_toornament_sync()`

```python
# Fix
db = SessionLocal()
try:
    generate_weeks(db)
    auto_lock_weeks(db)
finally:
    db.close()
```

---

### P2 — Dead Code / Incorrect Behaviour

#### 3. Unused `ThreadPoolExecutor`
**File:** `backend/main.py:293`

```python
_ingest_executor = ThreadPoolExecutor(max_workers=1)
```

Was used for the original one-shot startup ingest. Replaced by `_ingest_poll_loop` daemon thread, never removed. Delete it and its import.

#### 4. Duplicate week initialisation in lifespan
**File:** `backend/main.py:533–536`

```python
_db = SessionLocal()
generate_weeks(_db)
auto_lock_weeks(_db)
_db.close()
```

`_week_maintenance_loop` already calls both, but currently sleeps *first* — so weeks aren't ready for 5 min after startup. Fix: move the sleep to the end of the loop so the first iteration runs immediately, then remove the lifespan calls.

```python
def _week_maintenance_loop():
    while True:
        try:
            db = SessionLocal()
            generate_weeks(db)
            auto_lock_weeks(db)
        finally:
            db.close()
        time.sleep(_WEEK_CHECK_INTERVAL)  # sleep AFTER, not before
```

#### 5. Late imports inside functions
**File:** `backend/main.py:325` and `:1502`

`from toornament import sync_toornament_results` and `from schedule import get_schedule` are inside function bodies. Move to top-level imports.

---

### P3 — Duplication / Consolidation

#### 6. OpenDota retry logic in three places
**Affected files:** `backend/ingest.py` (`fetch_match_with_retry`), `backend/enrich.py` (inline sleep on 429), `backend/opendota_client.py`

`opendota_client.py` already exists as the right home. Add a single `get_json(url) -> dict` function there with unified exponential backoff + jitter, using the existing `_opendota_params()` for API key injection. Replace `fetch_match_with_retry` in `ingest.py` and the inline retry in `enrich.py` with calls to it.

#### 7. `SCHEDULE_SHEET_URL` defined twice
**Files:** `backend/schedule.py:14` (module constant) and `backend/main.py` (re-reads from `os.getenv`)

`main.py` should import `SCHEDULE_SHEET_URL` from `schedule` instead of calling `os.getenv()` again.

---

### P4 — Organisation

#### 8. Card image generation in `main.py` (249 lines)
**File:** `backend/main.py:41–289`

All PIL image functions (`generate_card_image`, `_circle_crop`, `_draw_centered_text`, etc.) and their constants (`_CARD_SIZE`, `_CARD_TEMPLATES`, `_FONT_PATHS`, etc.) have no FastAPI dependency.

**New file:** `backend/image.py` — pure move, zero logic change. `main.py` imports only `generate_card_image`. Removes ~250 lines from `main.py` and makes image logic independently testable.

#### 9. `SECRET_KEY` insecure default
**File:** `backend/main.py:551`

```python
# Current
secret_key=os.environ.get("SECRET_KEY", "dev-secret-change-me"),

# Fix — loud warning instead of silent weak key
_secret_key = os.environ.get("SECRET_KEY", "")
if not _secret_key:
    warnings.warn("[SECURITY] SECRET_KEY not set — using insecure default. Set SECRET_KEY in production.")
    _secret_key = "dev-secret-change-me"
```

Hard crash on missing key would break dev. A warning is the right balance.

---

## Critical Files

| File | Change |
|---|---|
| `backend/database.py` | Add `get_db()` generator dependency |
| `backend/main.py` | Apply `Depends(get_db)` everywhere; remove executor + duplicate week init; fix loop order; move late imports; SECRET_KEY warning |
| `backend/image.py` | **New** — extracted from `main.py:41–289`, pure move |
| `backend/opendota_client.py` | Add unified `get_json()` with exponential backoff + jitter |
| `backend/ingest.py` | Replace `fetch_match_with_retry` with `opendota_client.get_json()` |
| `backend/enrich.py` | Replace inline 429 sleep with `opendota_client.get_json()` |

---

## Execution Order

1. `database.py` — add `get_db` (additive, zero risk)
2. `image.py` — extract from `main.py` (pure move, reduces file size before the big edit)
3. `main.py` — apply `Depends(get_db)` across all endpoints (largest change)
4. `main.py` — remove executor, fix loop order, move imports, SECRET_KEY warning
5. `opendota_client.py` + `ingest.py` + `enrich.py` — consolidate retry

## Verification

- `docker compose -f docker-compose.yml -f docker-compose.dev.yml up --build` after each step
- Test login, card draw, and schedule endpoints after session management change
- Confirm week generation fires immediately on startup (not after 5 min delay)
- Confirm card image endpoint still works after `image.py` extraction
- Watch for `[SECURITY]` warning when `SECRET_KEY` is unset
