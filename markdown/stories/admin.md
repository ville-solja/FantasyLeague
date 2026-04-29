# Admin and Operations

## User Management

### Grant Tokens
**User story**
As an admin, I want to manually grant additional tokens to a specific user.

**Acceptance criteria**
- Admin can select any user and grant a specified number of tokens
- Token balance updates immediately
- Logged in the audit log with admin actor, target user, and amount

---

### Tester Account Flag
**User story**
As an admin, I want to mark any account as a tester so that it is excluded from public leaderboards.

**Acceptance criteria**
- The admin user list shows an "is tester" indicator for each account
- A toggle button next to each user switches `is_tester` on or off and gives inline confirmation
- Tester accounts are excluded from `GET /leaderboard/season` and `GET /leaderboard/weekly`
- Tester accounts remain visible (with a visual marker) in the admin users panel

---

## Promo Codes

### Generate Promo Codes
**User story**
As an admin, I want to create promo codes that grant tokens to users who redeem them.

**Acceptance criteria**
- Admin creates codes with a configurable token amount
- Each user can only redeem a given code once
- Admin can delete codes

---

## Scoring and Data

### Configure Scoring Weights
**User story**
As an admin, I want to configure the scoring weights for match stats.

**Acceptance criteria**
<<<<<<< HEAD
- Each stat weight (kills, assists, deaths, GPM, wards, tower damage) is editable from environment variables
- Rarity modifier percentages are also configurable
- Weight changes take effect for future calculations; use Recalculate to apply retroactively
=======
- Weights are stored in the database (`weights` table) and surfaced read-only in the Admin tab (`GET /weights`)
- Default values come from `backend/seed.py` (`DEFAULT_WEIGHTS`); optional startup overrides via `WEIGHTS_JSON` merge into DB on restart
- Tunables include per-stat weights for the scoring stat set (`kills`, `last_hits`, `denies`, `gold_per_min`, `obs_placed`, `towers_killed`, `roshan_kills`, `teamfight_participation`, `camps_stacked`, `rune_pickups`, `firstblood_claimed`, `stuns`), death formula params (`death_pool`, `death_deduction`), rarity bonuses (`rarity_*`), and modifier tuning (`modifier_count_*`, `modifier_bonus_pct`)
- Rarity modifier percentages are also configurable (same weight system)
- Changing DB weights affects scoring going forward; use **Recalculate** to recompute stored `player_match_stats.fantasy_points` (and downstream card/week totals) from the same stored raw stats
>>>>>>> 25cc59e (Initial commit)

---

### Recalculate Fantasy Points
**User story**
As an admin, I want to recalculate all historical fantasy points using the current scoring weights.

**Acceptance criteria**
- Recalculate button applies the current weights to all stored player-match stats
- Does not require re-fetching data from OpenDota
- Result shows the number of records updated
- Logged in the audit log

---

### Manual League Ingestion
**User story**
As an admin, I want to trigger data ingestion for a specific league at any time.

**Acceptance criteria**
- Admin can enter a league ID and trigger ingestion from the admin tab
- Ingestion fetches new matches, calculates fantasy points, seeds player cards, and enriches player profiles
- Already-stored matches are skipped (idempotent)
- Logged in the audit log

---

### Schedule Refresh
**User story**
As an admin, I want to force a refresh of the season schedule from the Google Sheet source.

**Acceptance criteria**
- Refresh button busts the in-memory schedule cache
- Fresh data is fetched immediately from the configured Google Sheets CSV URL
- Logged in the audit log

---

## Security and Integrity

### Server-side Validation
**Acceptance criteria**
- All state-changing actions (draw, activate, admin ops) are validated server-side
- Client-side `is_admin` flag alone is not sufficient — every admin endpoint re-verifies from the session
- Roster endpoint returns 403 if a user attempts to view another user's roster

---

### Audit Logs
**User story**
As an admin, I want visibility into actions that have taken place on the app.

**Acceptance criteria**
<<<<<<< HEAD
- Tracks: user registrations, logins, token draws, code redemptions, admin token grants, league ingestion, weight changes, recalculations, schedule refreshes, code creation and deletion, tester flag toggles
=======
- Tracks (non-exhaustive, current server actions): `user_register`, `user_login`, `password_reset_requested`, `token_draw`, `reroll_modifiers`, `token_redeem`, `admin_ingest`, `admin_recalculate`, `admin_schedule_refresh`, `admin_grant_tokens`, `admin_toggle_tester`, `admin_enrich_profiles`, `admin_set_match_week`, `admin_sync_match_weeks`, `admin_sync_toornament`, `admin_code_create`, `admin_code_delete`
>>>>>>> 25cc59e (Initial commit)
- Each entry includes timestamp, actor username, action type, and a detail string
- Visible in the Admin tab with most recent entries first
- Admin-only access

---

## Observability

### Build Version Display
**User story**
As a user reporting a bug, I want to see a faint version identifier on every page so that I can include the exact build in my report.

**Acceptance criteria**
- A version string is visible on every page in a small, low-contrast style
- Present regardless of login state
- Setting only `APP_VERSION` (image SHA) displays that value alone; setting both `APP_VERSION` and `APP_RELEASE` displays both (e.g. `v1.2.0 · b06e0c4`)
- Value is injected by CI as a Docker build argument and served via `/config`
