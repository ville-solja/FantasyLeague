# Demo Mode

An env-gated capability that lets an operator override the app's simulated "now" and seed
disposable accounts with random cards, so the season lifecycle (pre-lock → lock → scored) can
be demonstrated on demand using existing S15 data instead of waiting for real time to pass.
Structurally absent unless `DEMO_MODE=true` — never enable in production.

---

## Why this works with no changes to roster or scoring logic

Roster editability is gated purely by the persisted `Week.is_locked` flag, set once and
irreversibly by the auto-lock pass — not by a live comparison against wall-clock time at
request time. Weekly scoring (`GET /leaderboard/weekly`) is driven only by `week_id` and the
locked roster snapshot, with no time check at all. Demo Mode therefore only needs to control
one input — what "now" means to the week auto-lock/editability functions — to make all three
requested stages observable.

## Implementation

- `backend/models.py` — `DemoClock` singleton table (`id=1`, `override_timestamp`,
  `updated_at`). New table, so no `backend/migrate.py` entry is needed.
- `backend/clock.py` — `now(db)`, `get_override(db)`, `set_override(db, timestamp)`,
  `clear_override(db)`. `now(db)` returns the stored override only when `DEMO_MODE=true`
  *and* a row with a non-null `override_timestamp` exists; otherwise real wall-clock time.
- `backend/weeks.py` — `auto_lock_weeks`, `get_current_week`, and `get_next_editable_week`
  all read `now = clock.now(db)` instead of calling `time.time()` directly.
- `backend/twitch.py` — `GET /twitch/matches/current` (the Twitch extension's "current
  matches" panel, used when selecting an MVP) also reads `now = clock.now(db)`, so a demo
  walkthrough of the Twitch MVP flow reflects the dialed-in simulated time rather than real
  wall-clock time.
- `backend/routers/admin.py` — the four endpoints below. `_require_demo_mode()` is declared
  as a real FastAPI dependency (`Depends(_require_demo_mode)`) positioned *before*
  `Depends(require_admin)` in each signature, so a real HTTP request resolves it first: a
  non-admin (or unauthenticated) caller gets 404 when the mode is off, not 403/401 — the
  route's existence stays hidden. It is also called imperatively as the first line of each
  function body, since this codebase's test suite calls endpoint functions directly and
  bypasses FastAPI's dependency resolution entirely; a bare `Depends()` default never fires
  under that calling convention.
- `backend/routers/cards.py` — `draw_card` is reused unmodified, called as a plain Python
  function from `seed_demo_accounts` with a constructed `current_user` dict.

## Endpoints

All three endpoints return 404 (not 403) when `DEMO_MODE` is not `true`, so their existence
is not revealed on a production deployment. When reachable, all require an admin session.

### `GET /admin/demo/clock`
Returns `{"override_timestamp": <unix or null>, "effective_now": <unix>}`.

### `POST /admin/demo/clock`
Body: `{"timestamp": <unix>}`. Sets the demo clock override and synchronously re-runs the
week auto-lock pass, so any week whose `start_time` is now in the past locks immediately —
no waiting for the background maintenance interval. Logged as `admin_demo_clock_set`.

### `DELETE /admin/demo/clock`
Clears the override; the app falls back to real wall-clock time. Logged as
`admin_demo_clock_cleared`.

### `POST /admin/demo/seed-accounts`
Body: `{"count": 5, "cards_per_account": 3}` (both optional). Creates `demo1`, `demo2`, ...
accounts (skipping already-taken numbers), each granted `cards_per_account` tokens and drawn
that many cards via the existing draw mechanism (`draw_card`, called directly as a plain
Python function) — auto-activated into the roster up to `ROSTER_LIMIT`. If the player pool
is empty (or a draw otherwise fails), the account is still created with fewer cards rather
than aborting the whole batch. Returns each account's username and a one-time plaintext
password (bcrypt-hashed at rest via `hash_password`, exactly like real accounts). Logged as
`admin_demo_accounts_seeded`.

## Effect on background jobs

- The week auto-lock thread keeps running — it is the mechanism that reacts to the demo clock.
- The ingest poll thread (OpenDota polling) does not start when `DEMO_MODE=true`, since a
  demo walks through already-concluded, static season data and should not make outbound API
  calls or risk overwriting curated demo state.

## Known limitation

Moving the demo clock backward does not unlock an already-locked week — locking is
irreversible by design, matching production behaviour. The demo clock can only move a week
*forward* through pre-lock → locked; it cannot reverse a transition once triggered.

## App Config

`GET /config` includes `"demo_mode": true` only when the server has `DEMO_MODE=true` set
(read live from the environment on every request, not cached at startup). The frontend
(`frontend/app-globals.js` `loadConfig()`) stores this as `window.demoMode`, toggles the
`#demo-mode-badge` fixed banner, and calls `renderDemoModePanel()` (`frontend/app-admin.js`),
which injects the Settings-tab Demo Mode panel (clock form + seed-accounts form and results
table) into `#demoModePanelContainer` only when true — the container is left empty otherwise,
so the panel markup is entirely absent from the DOM, not just hidden via CSS.

## Startup behaviour

`backend/main.py`'s `lifespan()` logs a `[DEMO MODE] ... NEVER enable in production` warning
and skips starting the `_ingest_poll_loop` background thread (no outbound OpenDota calls)
when `DEMO_MODE=true`. The `_week_maintenance_loop` thread (which calls `auto_lock_weeks`)
always starts — it is the mechanism that reacts to the demo clock.

## Configuration

| Variable | Default | Description |
|---|---|---|
| `DEMO_MODE` | *(unset/false)* | Enables the demo clock override and account-seeding endpoints, and disables the OpenDota ingest poll thread. **Never set in production.** |
