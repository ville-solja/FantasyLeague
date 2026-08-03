# Admin Router Organization

Reference doc for where admin endpoints live after `backend/routers/admin.py`
(formerly a single 1,236-line file) was split into ten focused sub-routers. Aimed at
contributors and agents locating admin endpoint code — not a user-facing feature.

---

## Module map

Each module is a self-contained `APIRouter()` mounted in `backend/main.py`, mirroring the
existing per-router pattern used for `players`, `auth`, `profile`, `leaderboard`, and `cards`.

| Module | Covers |
|---|---|
| `backend/routers/admin_users.py` | User list, tester toggle, token grants, promo codes CRUD, `/redeem`, token-grant-events |
| `backend/routers/admin_ingest.py` | Manual league ingest trigger, recalculate, schedule endpoints, match-week assignment, Toornament sync, profile enrichment trigger |
| `backend/routers/admin_weeks.py` | Week CRUD (create/edit/delete, date-only inputs) |
| `backend/routers/admin_notifications.py` | Admin-configured broadcast notifications CRUD |
| `backend/routers/admin_tags.py` | Tag definitions CRUD, user tag grant/revoke |
| `backend/routers/admin_players.py` | Player pool management (add/bulk-add/remove, with token refunds) |
| `backend/routers/admin_leagues.py` | Monitored league list/monitor/unmonitor/purge |
| `backend/routers/admin_season.py` | Season lifecycle (End Season archive, Season Reset), audit log |
| `backend/routers/admin_matches.py` | Admin match table, MVP selection |
| `backend/routers/admin_demo.py` | Demo Mode clock override and disposable account seeding |

No endpoint path, request/response shape, or auth guard changes as part of this split — it is
a pure file reorganization of what previously all lived in `backend/routers/admin.py`.

---

*This document is a stub created at feature planning time. Fill in implementation details once
the feature is built.*
