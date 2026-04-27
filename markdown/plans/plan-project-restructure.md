# Plan: Project Structure Reorganization

## Context
Three structural problems make the codebase hard to navigate. `backend/main.py` is 1,553 lines with 50 endpoints all registered directly on `app` — no routers, no grouping. `frontend/app.js` is 1,719 lines of mixed global-scope code covering every tab and modal. `markdown/feature_description/` is a legacy orphaned directory (17 files) that predates the current `markdown/features/` hierarchy and is not referenced by any agent or CLAUDE.MD. This plan splits the two monolithic files into logical modules and removes the orphaned docs. No API surface changes, no new dependencies, no behaviour changes.

---

## Phase 1 — Documentation Cleanup

Delete:
- `markdown/feature_description/` — entire directory (17 files, orphaned legacy, diverges from `markdown/features/`)
- `markdown/user_stories.md` — redirect stub, superseded by `markdown/stories/_index.md`
- `debug_jwt.py` — temporary debug script in project root

---

## Phase 2 — Backend: Extract Shared Infrastructure

### Critical Files
| File | Change |
|---|---|
| `backend/deps.py` | **Create** — `get_current_user`, `require_admin`, `_audit` |
| `backend/card_utils.py` | **Create** — all card scoring/modifier helpers |
| `backend/routers/__init__.py` | **Create** — empty package marker |
| `backend/main.py` | Add temporary `from deps import ...` and `from card_utils import *` aliases |

### Step 1 — Create `backend/deps.py`
Cut from `main.py` and place here:
- `get_current_user` (~lines 140–175)
- `require_admin` (~line 178)
- `_audit()` (~lines 180–188)

Add to `main.py`: `from deps import get_current_user, require_admin, _audit`

### Step 2 — Create `backend/card_utils.py`
Cut from `main.py`:
- `_load_weights()`, `_stat_sums_from_row()`, `_compute_card_points()`
- `_assign_modifiers()`, `_card_modifiers_map()`, `_card_modifiers_dict_for_image()`, `_format_modifiers()`

Add to `main.py`: `from card_utils import *`

### Step 3 — Create `backend/routers/__init__.py` (empty)

**Verify after each step:** `cd backend && python -c "import main"`

---

## Phase 3 — Backend: Extract Routers

Each router: create file → use `router = APIRouter()` → move endpoints (`@app.X` → `@router.X`) → add `app.include_router(X_router)` in `main.py` → delete endpoints from `main.py` → verify.

### Critical Files
| File | Endpoints |
|---|---|
| `backend/routers/players.py` | `/players/*`, `/teams/*`, `/admin/enrich-profiles` |
| `backend/routers/auth.py` | `/login`, `/register`, `/logout`, `/forgot-password` |
| `backend/routers/profile.py` | `/me`, `/profile/*`, `/profile/username`, `/profile/player-id`, `/profile/password` |
| `backend/routers/leaderboard.py` | `/top`, `/leaderboard*`, `/weights`, `/simulate*`; local `_leaderboard_rows()` |
| `backend/routers/cards.py` | `/deck`, `/draw`, `/weeks`, `/cards/*`, `/roster/*`; local `_build_roster_response()`, `_LATEST_TEAM_SUBQUERY` |
| `backend/routers/admin.py` | `/admin/*`, `/users*`, `/ingest/*`, `/schedule*`, `/matches/*`, `/codes*`, `/redeem`, `/grant-tokens`, `/recalculate`, `/audit-logs` |
| `backend/main.py` | Reduced to: imports, env constants, `lifespan` + background threads, middleware, `app.include_router()` calls, `/health`, `/config` |

**Extraction order** (least to most dependencies — extract in this sequence):
1. `routers/players.py` — only `get_db`, `require_admin`, models, `run_profile_enrichment`
2. `routers/auth.py` — adds `hash_password`, `send_email`, `_audit`
3. `routers/profile.py` — adds `verify_password`, `get_current_user`
4. `routers/leaderboard.py` — adds `card_utils.*`, `scoring.*`
5. `routers/cards.py` — adds `image.*`, `weeks.*`
6. `routers/admin.py` — last; needs everything

**Import rules:**
- `get_db` → import from `database`
- `get_current_user`, `require_admin`, `_audit` → import from `deps`
- Card helpers → import from `card_utils`
- `INITIAL_TOKENS`, `ROSTER_LIMIT` → re-read via `os.getenv()` in each router that needs them
- `TOKEN_NAME`, `_APP_VERSION`, `_APP_RELEASE` → stay in `main.py` (only used in `/config`)

---

## Phase 4 — Frontend: Split `app.js` into 9 Files

All files use global scope (no ES modules). Load order in `index.html` is critical.

### Critical Files
| File | Contents |
|---|---|
| `frontend/app-globals.js` | `API`, all shared state vars, `setStatus()`, `_escHtml()`, `playerLink()`, `teamLink()`, `loadConfig()`, `updateTokenDisplay()`, `bumpCardImageCacheBust()`, `cardImageUrl()`, `switchTab()` |
| `frontend/app-auth.js` | `applyAuthState()`, login/register/logout flows, `loadMe()`, `_applyTempPasswordBanner()` |
| `frontend/app-cards.js` | `loadDeck()`, `drawCard()`, draw-reveal animation helpers, `showCard()`, `showReveal()`, `closeReveal()`, reroll confirm flow |
| `frontend/app-roster.js` | `_rosterCards`, `_weeks`, `_rosterWeekId` state, `loadWeeks()`, `loadRoster()`, `_cardSlotHTML()`, activate/deactivate, `redeemCode()` |
| `frontend/app-players.js` | `loadPlayers()`, `filterPlayers()`, `loadTeams()`, player modal, team modal, `loadSchedule()` |
| `frontend/app-leaderboard.js` | `loadSeasonLeaderboard()`, `loadWeeklyLeaderboard()`, `_lbStandingsRow()`, `loadLeaderboard()`, `loadTop()`, week select |
| `frontend/app-admin.js` | `loadWeights()`, `loadUsers()`, `toggleTester()`, `grantTokens()`, codes, schedule refresh, ingest, audit log, recalculate |
| `frontend/app-profile.js` | `loadProfile()`, Twitch link status, `generateTwitchCode()`, `saveUsername()`, `changePassword()`, `savePlayerId()` |
| `frontend/app-init.js` | `init()` function + DOMContentLoaded bootstrap call |

**Note:** Declare `let _weeks = []` in `app-globals.js`; `loadWeeks()` in `app-roster.js` populates it; `_populateLbWeekSelect()` in `app-leaderboard.js` reads it safely because all scripts parse before any tab switch.

### Modify `frontend/index.html`
Replace `<script src="/app.js"></script>` with:
```html
<script src="/app-globals.js"></script>
<script src="/app-auth.js"></script>
<script src="/app-cards.js"></script>
<script src="/app-roster.js"></script>
<script src="/app-players.js"></script>
<script src="/app-leaderboard.js"></script>
<script src="/app-admin.js"></script>
<script src="/app-profile.js"></script>
<script src="/app-init.js"></script>
```

Delete `frontend/app.js` after smoke test passes.

---

## Verification

### Backend (after each router extraction)
```bash
cd backend && python -c "import main"
cd backend && python -m pytest tests/ -q
```

### Backend (final — confirm route count unchanged)
```bash
cd backend && python -c "import main; print(len(main.app.routes), 'routes')"
```

### Frontend (browser smoke test)
1. All 9 script tags return HTTP 200, no JS errors on load
2. Leaderboard tab renders unauthenticated
3. Login → session set, My Team tab appears, token balance shows
4. Draw card — modal opens, reveal animates
5. Roster — week selector renders, activate/deactivate works
6. Players tab — player list renders, player modal opens
7. Admin tab — weights, users, codes, audit log all load
8. Profile tab — username pre-filled, Twitch link status renders

Any `ReferenceError: X is not defined` means a function was placed in a later file than needed — move it to `app-globals.js`.
