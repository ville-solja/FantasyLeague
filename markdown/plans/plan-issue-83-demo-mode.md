# Plan: Demo Mode

## Context

Kana Cards is currently between seasons, which makes it hard to reliably show the season
lifecycle — pre-lock roster editing, the lock transition, and post-week scoring — since real
time only moves forward once and matches only exist while a season is live. Demo Mode adds an
env-gated capability, invisible in production, that lets an operator override the app's notion
of "now" and instantly re-run the auto-lock transition, plus seed disposable demo accounts
pre-loaded with random cards to hand out to people trying the tool. It reuses the existing
S15 data and the existing week-lock/scoring machinery rather than building a parallel system.

Investigation finding that shapes this plan: roster editability is gated purely by the
persisted `Week.is_locked` flag (set once, irreversibly, by `auto_lock_weeks`) — not by a live
comparison against wall-clock time at request time. Weekly scoring (`GET /leaderboard/weekly`)
is likewise driven only by `week_id` and the locked roster snapshot, with no time check at
all. This means the three requested "stages" are already fully reproducible by controlling a
single input: what `auto_lock_weeks`, `get_current_week`, and `get_next_editable_week` treat
as "now." No changes are needed to roster edit endpoints, scoring, or leaderboard code.

Assumptions (flagged for review):
- Demo Mode is a single global clock override per deployment (not per-session) — consistent
  with it being a separate, isolated deployment (`DEMO_MODE=true`) rather than a mode toggled
  within the production instance.
- Moving the demo clock backward does not unlock already-locked weeks, matching the existing
  "locking is irreversible" invariant. Documented as a known limitation, not a bug.
- The ingest poll thread (which fetches new OpenDota matches) is skipped entirely when
  `DEMO_MODE=true`, since a demo walks through already-concluded, static season data and
  should not make outbound calls to OpenDota or risk overwriting curated demo state. The
  week auto-lock thread keeps running — it is the mechanism that reacts to the demo clock.

Resolves GitHub issue #83.

---

## User Stories

### Move the Demo Clock
**User story**
As an operator running a demo deployment, I want to set the app's simulated "now" to any
point in time so that I can walk a viewer through pre-lock, lock, and post-week scoring on
demand instead of waiting for real time to pass.

**Acceptance criteria**
- `POST /admin/demo/clock` (body `{"timestamp": <unix>}`) is only reachable when
  `DEMO_MODE=true`; returns 404 when the env var is unset or false, regardless of admin status
- When reachable, it requires an admin session like other admin endpoints
- Setting the clock immediately (synchronously, in the same request) re-runs the auto-lock
  pass, so any week whose `start_time` has now passed under the new simulated time locks
  right away — no waiting for the background maintenance interval
- `GET /admin/demo/clock` returns the current override and the effective "now" it produces
- `DELETE /admin/demo/clock` clears the override; the app falls back to real wall-clock time
- Every read of "now" used for week locking and editability (`auto_lock_weeks`,
  `get_current_week`, `get_next_editable_week`) uses the override when one is set

---

### See Demo Mode Reflected in the App
**User story**
As anyone using a demo deployment, I want the app to visibly indicate that I'm in a demo so
that I understand roster locks and scores are being driven by a simulated clock, not real
time.

**Acceptance criteria**
- `GET /config` includes `demo_mode: true` only when `DEMO_MODE=true` is set on the server
- The frontend shows a small persistent badge when `demo_mode` is true (any tab)
- The Settings tab's admin panel shows the Demo Mode section (clock control + account seeding)
  only when `demo_mode` is true; it is entirely absent otherwise, including in the DOM

---

### Seed Demo Accounts
**User story**
As an operator, I want to generate a batch of disposable accounts pre-loaded with a few
random cards so that I can hand out ready-to-explore logins to people trying the tool.

**Acceptance criteria**
- `POST /admin/demo/seed-accounts` (body `{"count": 5, "cards_per_account": 3}`, both optional
  with sane defaults) is only reachable when `DEMO_MODE=true`; 404 otherwise
- Requires an admin session
- Creates that many new users named `demo1`, `demo2`, ... (skipping numbers already taken, so
  repeated calls add more accounts rather than colliding)
- Each account receives `cards_per_account` cards via the existing draw mechanism (weighted
  rarity, real player pool), auto-activated into its roster up to `ROSTER_LIMIT`
- The response includes each generated username and a one-time plaintext password (bcrypt
  hashed at rest, exactly like real accounts) so the operator can distribute them
- Logged to the audit log as `admin_demo_accounts_seeded`

---

### Guard Against Accidental Production Exposure
**User story**
As an operator, I want Demo Mode to be structurally incapable of running in production so
that a misconfigured deployment can't let a stranger rewrite the server's clock.

**Acceptance criteria**
- `DEMO_MODE` defaults to unset/false; all three demo endpoints return 404 (not 403) when it
  is not explicitly `true`, so their existence is not revealed
- The app logs a prominent warning at startup when `DEMO_MODE=true`, mirroring the existing
  `SECRET_KEY`-insecure-default and `TWITCH_LOCAL_DEV` warnings
- `.env.example` documents `DEMO_MODE` with an explicit "never set in production" note
- The background ingest poll thread does not start when `DEMO_MODE=true`; the week
  maintenance (auto-lock) thread continues to run

---

## Implementation

### Critical Files

| File | Change |
|---|---|
| `backend/models.py` | New `DemoClock` singleton table (new table — no migration entry needed) |
| `backend/clock.py` | New module: `now(db) -> int`, `get_override(db)`, `set_override(db, ts)`, `clear_override(db)` |
| `backend/weeks.py` | `auto_lock_weeks`, `get_current_week`, `get_next_editable_week` call `clock.now(db)` instead of `time.time()` |
| `backend/routers/admin.py` | `GET/POST/DELETE /admin/demo/clock`, `POST /admin/demo/seed-accounts`, all gated on `DEMO_MODE` |
| `backend/main.py` | `GET /config` gains `demo_mode`; skip starting `_ingest_poll_loop` when `DEMO_MODE=true`; startup warning log |
| `.env.example` | Document `DEMO_MODE` |
| `frontend/app-globals.js` | Read `demo_mode` from `/config`; show/hide demo badge and Settings panel |
| `frontend/index.html` | Demo Mode badge; Demo Mode panel in Settings tab (clock form, seed-accounts form + results) |
| `frontend/app-admin.js` | Demo clock get/set/clear calls; seed-accounts call and credential display |

### Step 1 — `DemoClock` model and `clock.py` helper

```python
class DemoClock(Base):
    __tablename__ = "demo_clock"
    id                 = Column(Integer, primary_key=True)  # always 1
    override_timestamp = Column(Integer, nullable=True)
    updated_at         = Column(Integer, nullable=True)
```

```python
# backend/clock.py
import os
import time
from models import DemoClock

def _demo_enabled() -> bool:
    return os.getenv("DEMO_MODE", "").lower() == "true"

def now(db) -> int:
    if _demo_enabled():
        row = db.get(DemoClock, 1)
        if row and row.override_timestamp is not None:
            return row.override_timestamp
    return int(time.time())

def get_override(db) -> int | None:
    row = db.get(DemoClock, 1)
    return row.override_timestamp if row else None

def set_override(db, timestamp: int) -> None:
    row = db.get(DemoClock, 1)
    if not row:
        row = DemoClock(id=1)
        db.add(row)
    row.override_timestamp = timestamp
    row.updated_at = int(time.time())

def clear_override(db) -> None:
    row = db.get(DemoClock, 1)
    if row:
        row.override_timestamp = None
        row.updated_at = int(time.time())
```

### Step 2 — Route `weeks.py` through the demo clock

Replace the three `now = int(time.time())` lines in `auto_lock_weeks`, `get_current_week`,
and `get_next_editable_week` with `now = clock.now(db)`. No other logic in these functions
changes — they already only consume `now` as an integer.

### Step 3 — Demo clock endpoints

```python
def _require_demo_mode():
    if os.getenv("DEMO_MODE", "").lower() != "true":
        raise HTTPException(status_code=404)

@router.get("/admin/demo/clock")
def get_demo_clock(db=Depends(get_db), _: dict = Depends(require_admin)):
    _require_demo_mode()
    override = clock.get_override(db)
    return {"override_timestamp": override, "effective_now": clock.now(db)}

@router.post("/admin/demo/clock")
def set_demo_clock(body: DemoClockBody, db=Depends(get_db),
                   admin: dict = Depends(require_admin)):
    _require_demo_mode()
    clock.set_override(db, body.timestamp)
    auto_lock_weeks(db)  # synchronous — make the transition observable immediately
    _audit(db, "admin_demo_clock_set", actor_id=admin["user_id"],
           actor_username=admin["username"], detail=f"timestamp={body.timestamp}")
    db.commit()
    return {"override_timestamp": body.timestamp, "effective_now": clock.now(db)}

@router.delete("/admin/demo/clock")
def clear_demo_clock(db=Depends(get_db), admin: dict = Depends(require_admin)):
    _require_demo_mode()
    clock.clear_override(db)
    _audit(db, "admin_demo_clock_cleared", actor_id=admin["user_id"],
           actor_username=admin["username"], detail="")
    db.commit()
    return {"override_timestamp": None}
```

Note `_require_demo_mode` must run before any other logic so a disabled deployment 404s
immediately rather than leaking behaviour through timing or error-shape differences.

### Step 4 — Seed demo accounts endpoint

```python
@router.post("/admin/demo/seed-accounts")
def seed_demo_accounts(body: SeedDemoAccountsBody, db=Depends(get_db),
                       admin: dict = Depends(require_admin)):
    _require_demo_mode()
    count = body.count or 5
    cards_per_account = body.cards_per_account or 3
    existing = {u.username for u in db.query(User).filter(User.username.like("demo%")).all()}
    created = []
    n = 1
    while len(created) < count:
        username = f"demo{n}"
        n += 1
        if username in existing:
            continue
        password = secrets.token_urlsafe(9)
        user = User(username=username, email=f"{username}@demo.local",
                    password_hash=hash_password(password),
                    tokens=cards_per_account)
        db.add(user)
        db.flush()
        fake_current_user = {"user_id": user.id, "username": username, "is_admin": False}
        for _ in range(cards_per_account):
            draw_card(db=db, current_user=fake_current_user)
        created.append({"username": username, "password": password})
    _audit(db, "admin_demo_accounts_seeded", actor_id=admin["user_id"],
           actor_username=admin["username"], detail=f"created={len(created)}")
    db.commit()
    return {"accounts": created}
```

Reuses `draw_card` from `routers/cards.py` directly — it already handles rarity rolls, player
selection, modifier assignment, and roster auto-activation up to `ROSTER_LIMIT`. Granting
`cards_per_account` tokens up front lets the loop call the real draw path unmodified.

### Step 5 — `/config`, startup warning, and skip live ingest polling

- Add `"demo_mode": os.getenv("DEMO_MODE", "").lower() == "true"` to the `GET /config` response.
- In `lifespan()`, log `logger.warning("[DEMO MODE] ... never enable in production")` when the
  env var is true, alongside the existing `SECRET_KEY` warning pattern.
- Wrap the `threading.Thread(target=_ingest_poll_loop, ...)` start call in
  `if not _demo_mode: ...` so no outbound OpenDota polling happens in a demo deployment.

### Step 6 — Frontend

- `app-globals.js`: after loading `/config`, store `window.demoMode = config.demo_mode` and
  toggle a `#demo-mode-badge` element's visibility.
- `index.html`: small fixed badge (e.g. "DEMO MODE") shown only via JS when `demo_mode` is
  true; a "Demo Mode" panel in the Settings tab with a datetime input + Set/Clear buttons for
  the clock, and a count input + "Seed Accounts" button whose response renders a table of
  generated username/password pairs for the operator to copy.
- `app-admin.js`: `loadDemoClock()`, `setDemoClock()`, `clearDemoClock()`, `seedDemoAccounts()`
  — all no-ops if `demo_mode` is false (panel isn't rendered, so buttons don't exist).

---

## Verification

- With `DEMO_MODE` unset: all three `/admin/demo/*` endpoints return 404 for both admin and
  non-admin sessions; `/config` omits or falses `demo_mode`; Settings tab shows no demo panel;
  ingest poll thread starts as normal
- With `DEMO_MODE=true`: startup log shows the warning; ingest poll thread does not start;
  `/config` returns `demo_mode: true`
- Create an unlocked week with `start_time` a few minutes in the future (real time). Call
  `POST /admin/demo/clock` with a timestamp past that `start_time` → response confirms the
  week is now locked (check `GET /admin/weeks`), a roster snapshot exists, and the weekly
  token grant fired — all without waiting for the real maintenance interval
- Roster edits are blocked for the now-locked week and remain allowed for a week whose
  (real-or-demo) start time is still in the future
- `GET /leaderboard/weekly?week_id=<locked demo week>` returns scoring immediately after lock
- `POST /admin/demo/seed-accounts` with `count=3, cards_per_account=2` creates 3 new users,
  each with 2 active cards and a returned plaintext password that successfully logs in
- Calling seed-accounts again does not collide with or overwrite the first batch
- Non-admin sessions get 403 (not 404) on all three endpoints when `DEMO_MODE=true` — 404 is
  reserved for the mode being off
- Moving the demo clock backward after a week has locked does not unlock it (documented
  limitation, not re-tested as a bug)
