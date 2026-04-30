# Plan: Project Structure Reorganization

## Context
Three structural problems make the codebase hard to navigate. `backend/main.py` is 1,636 lines with 51 endpoints all registered directly on `app` — no routers, no grouping. `frontend/app.js` is 1,829 lines of mixed global-scope code covering every tab and modal. `markdown/feature_description/` is a legacy orphaned directory (17 files) that predates the current `markdown/features/` hierarchy and is not referenced by any agent or CLAUDE.MD. This plan splits the two monolithic files into logical modules and removes the orphaned docs. No API surface changes, no new dependencies, no behaviour changes.

Several backend modules already exist as separate files and do not need to be created:
- `backend/auth.py` — `hash_password`, `verify_password`
- `backend/database.py` — `get_db`, `SessionLocal`, `Base`, `engine`
- `backend/email_utils.py` — `send_email`
- `backend/dotabuff_league_logos.py` — logo scraping/caching
- `backend/opendota_client.py` — rate-limited OpenDota HTTP client

The remaining extraction targets are `get_current_user` / `require_admin` / `_audit` (still in `main.py`), card helpers, and the router groupings.

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
| `backend/main.py` | Add `from deps import ...` and `from card_utils import *` aliases |

### Step 1 — Create `backend/deps.py`
Cut from `main.py` and place here:
- `get_current_user` (~lines 173–179)
- `require_admin` (~line 181)
- `_audit()` (~lines 187–196)

Imports needed: `Request`, `HTTPException`, `Depends`, `SessionLocal`, `AuditLog`.

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
| `backend/routers/players.py` | `GET /players`, `GET /players/{id}`, `GET /players/{id}/profile`, `GET /teams`, `GET /teams/{id}` |
| `backend/routers/auth.py` | `POST /login`, `POST /register`, `POST /logout`, `POST /forgot-password` |
| `backend/routers/profile.py` | `GET /me`, `GET /profile/{user_id}`, `PUT /profile/username`, `PUT /profile/player-id`, `PUT /profile/password` |
| `backend/routers/leaderboard.py` | `GET /top`, `GET /leaderboard`, `GET /leaderboard/roster`, `GET /leaderboard/season`, `GET /leaderboard/weekly`, `GET /weights`, `GET /simulate`, `POST /simulate/{match_id}`; local `_leaderboard_rows()` |
| `backend/routers/cards.py` | `GET /deck`, `POST /draw`, `GET /weeks`, `GET /cards/{id}`, `GET /cards/{id}/image`, `POST /roster/{id}/reroll`, `POST /roster/{id}/activate`, `POST /roster/{id}/deactivate`, `GET /roster/{user_id}`; local `_build_roster_response()`, `_LATEST_TEAM_SUBQUERY` |
| `backend/routers/admin.py` | `POST /ingest/league/{id}`, `GET /users`, `POST /users/{id}/toggle-tester`, `POST /grant-tokens`, `POST /recalculate`, `GET /schedule`, `POST /schedule/refresh`, `GET /schedule/debug`, `PUT /matches/{id}/week`, `POST /admin/sync-match-weeks`, `POST /admin/sync-toornament`, `POST /admin/enrich-profiles`, `POST /admin/top-up-cards`, `POST /codes`, `GET /codes`, `DELETE /codes/{id}`, `POST /redeem`, `GET /audit-logs` |
| `backend/main.py` | Reduced to: imports, env constants, `lifespan` + background threads, middleware, `app.include_router()` calls, `GET /health`, `GET /config` |

**Extraction order** (least to most dependencies — extract in this sequence):
1. `routers/players.py` — only `get_db`, `require_admin`, models, `run_profile_enrichment` (from `enrich.py`)
2. `routers/auth.py` — adds `hash_password` (from `auth.py`), `send_email` (from `email_utils.py`), `_audit`
3. `routers/profile.py` — adds `verify_password` (from `auth.py`), `get_current_user`
4. `routers/leaderboard.py` — adds `card_utils.*`, `scoring.*`
5. `routers/cards.py` — adds `image.*`, `weeks.*`
6. `routers/admin.py` — last; needs everything

**Import rules:**
- `get_db` → import from `database`
- `hash_password`, `verify_password` → import from `auth`
- `send_email` → import from `email_utils`
- `get_current_user`, `require_admin`, `_audit` → import from `deps`
- Card helpers → import from `card_utils`
- `INITIAL_TOKENS`, `ROSTER_LIMIT` → re-read via `os.getenv()` in each router that needs them
- `TOKEN_NAME`, `_APP_VERSION`, `_APP_RELEASE` → stay in `main.py` (only used in `GET /config`)

---

## Phase 4 — Frontend: Split `app.js` into 9 Files

All files use global scope (no ES modules). Load order in `index.html` is critical.

### Critical Files
| File | Contents |
|---|---|
| `frontend/app-globals.js` | `API`, all shared state vars (`activeUserId`, `activeUsername`, `activeIsAdmin`, `activeMustChangePassword`, `_tokenName`, `_tokenBalance`, `_cardImageBustSeq`), `setStatus()`, `_escHtml()`, `playerLink()`, `teamLink()`, `loadConfig()`, `updateTokenDisplay()`, `bumpCardImageCacheBust()`, `cardImageUrl()`, `switchTab()`, `toggleScoringInfo()` |
| `frontend/app-auth.js` | `applyAuthState()`, `showLogin()`, `showForgotPassword()`, `submitForgotPassword()`, `closeLoginModal()`, `closeRegisterModal()`, `showRegister()`, `_regFieldErr()`, `_regClearField()`, `_regClearErrors()`, `login()`, `register()`, `logout()`, `loadMe()`, `_applyTempPasswordBanner()` |
| `frontend/app-cards.js` | `loadDeck()`, `drawCard()`, draw-reveal animation helpers (`_normalizeDrawRarity`, `_stripDrawBurstClasses`, `_stripRevealImgWrapRarity`, `_prefersReducedMotion`, `_stripRevealDrawFx`, `DRAW_REVEAL_MIN_MS`, `DRAW_REVEAL_FLASH_MS`, `DRAW_RARITY_KEYS`, `_drawBurstHideTimer`, `REROLL_IMAGE_MIN_MS`), `showCard()`, `showReveal()`, `closeReveal()`, `openRerollConfirm()`, `closeRerollConfirm()`, `confirmReroll()`, `_openCardId` |
| `frontend/app-roster.js` | `_rosterCards`, `_rosterWeekId` state, `showRosterCard()`, `loadWeeks()`, `_renderWeekSelector()`, `onRosterWeekChange()`, `loadRoster()`, `_cardSlotHTML()`, `activateCard()`, `deactivateCard()`, `redeemCode()` |
| `frontend/app-players.js` | `_playersData`, `loadPlayers()`, `filterPlayers()`, `renderPlayers()`, `loadTeams()`, `openPlayerModal()`, `renderPlayerProfile()`, `closePlayerModal()`, `openTeamModal()`, `closeTeamModal()`, `loadSchedule()`, `showPlayerPreview()` |
| `frontend/app-leaderboard.js` | `onLbWeekChange()`, `toggleLbDetail()`, `_lbStandingsRow()`, `loadSeasonLeaderboard()`, `loadWeeklyLeaderboard()`, `_populateLbWeekSelect()`, `_allLeaderboardRows`, `loadLeaderboard()`, `_renderLeaderboard()`, `loadTop()` |
| `frontend/app-admin.js` | `loadWeights()`, `loadUsers()`, `toggleTester()`, `grantTokens()`, `loadCodes()`, `createCode()`, `deleteCode()`, `refreshSchedule()`, `ingestLeague()`, `loadAuditLog()`, `recalculate()`, `enrichProfiles()` |
| `frontend/app-profile.js` | `loadProfile()`, `_renderTwitchLinkStatus()`, `_twitchCodeTimer`, `generateTwitchCode()`, `saveUsername()`, `changePassword()`, `savePlayerId()` |
| `frontend/app-init.js` | `loadHowToPlay()`, `init()` function + DOMContentLoaded bootstrap call |

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
Expected: 51 routes (plus framework internals).

### Frontend (browser smoke test)
1. All 9 script tags return HTTP 200, no JS errors on load
2. Leaderboard tab renders unauthenticated
3. Login → session set, My Team tab appears, token balance shows
4. Draw card — modal opens, reveal animates
5. Roster — week selector renders, activate/deactivate works
6. Players tab — player list renders, player modal opens with profile section
7. Admin tab — weights, users, codes, audit log, enrich profiles all load
8. Profile tab — username pre-filled, Twitch link status renders
9. How to Play tab — scoring table and death pool description render

Any `ReferenceError: X is not defined` means a function was placed in a later file than needed — move it to `app-globals.js`.
