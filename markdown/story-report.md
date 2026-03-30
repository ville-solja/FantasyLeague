<!-- Generated automatically by scripts/story_report.py — do not edit by hand -->
_Last updated: 2026-03-30 05:34 UTC_

# Story Coverage Report

| ID | Story | Status | Notes |
|----|-------|--------|-------|
| 1.1 | User Registration | ✅ Aligned | `/register` endpoint checks unique username/email, creates user, grants initial tokens, records `created_at` timestamp. |
| 1.2 | User Login | ⚠️ Diverged | `/login` validates credentials and returns user data, but error message is "Invalid username or password" instead of required "Login failed – Invalid credentials." No server-side session/token management; auth state is client-side localStorage only — session persistence and route protection are not enforced server-side. |
| 1.3 | User Receive Temporary Password | 🔲 Not implemented | No forgot-password or temporary password email flow exists anywhere in the codebase. |
| 1.4 | User Password Reset | ✅ Aligned | `/profile/password` endpoint allows logged-in user to change password via current+new password flow; UI present in Profile tab. |
| 1.5 | User Logout | ⚠️ Diverged | Client-side `logout()` clears localStorage and redirects to leaderboard tab. However, there is no server-side session to invalidate. Logout button is only in the header, satisfying "from any page." |
| 1.6 | Admin-only Access | ✅ Aligned | `require_admin()` gate on admin endpoints; admin tab hidden for non-admins via `applyAuthState()`. |
| 2.1 | Grant Starter Tokens on Registration | ✅ Aligned | `INITIAL_TOKENS` (default 5) granted at registration. |
| 2.2 | Token Visibility | ✅ Aligned | `tokenBalance` element displayed across all tabs in the header. |
| 2.3 | View Cards | ⚠️ Diverged | Cards show player name, rarity (card_type), and team name. Modifiers are not displayed because the Card model has no modifier fields. Cards visible in My Team tab with active/bench distinction. |
| 2.4 | View Weekly Rosters | ✅ Aligned | Upcoming week's roster is default view; week selector exists. Carryover logic is implicit (cards remain active). Lock timing shown via `rosterWeekStatus`. However, lock time is described as "every Sunday at end of day" but actual lock logic is in `weeks.py` (not provided) — assumed aligned. |
| 2.5 | View Current and Season Points | ✅ Aligned | Weekly points and season total displayed in roster view. New user starts at 0. Week history selector allows viewing past weeks. |
| 2.6 | View Collection | 🔲 Not implemented | Post-MVP; no separate Collection tab exists. |
| 3.1 | Generate Cards | ⚠️ Diverged | `seed_cards()` generates cards per player, and admin can ingest by league ID. However, there is no endpoint to import by player ID list. Card distribution per player is defined in `seed.py` (not shown) — cannot verify 1/2/4/8 rarity distribution. Duplicate avoidance in pool is unverifiable without `seed.py`. |
| 3.2 | Card Drawing | ⚠️ Diverged | User can draw a card with token deduction; card shown and auto-placed to active or bench. However, drawn cards lack modifier display since modifiers don't exist on the Card model. |
| 3.3 | Remove Cards from Pool | 🔲 Not implemented | Post-MVP; no admin endpoint to remove a player's cards or refund tokens. |
| 3.4 | Assign Randomized Card Rarity | ⚠️ Diverged | Cards have a `card_type` (rarity) but it's assigned during deck generation (`seed_cards`), not randomized at draw time. The pool has pre-set rarity counts per player. Story says "cards that are generated have a rarity" — this is met, but randomization at draw depends on interpretation. |
| 3.5 | Assign Randomized Modifiers | 🔲 Not implemented | Card model has no modifier columns. No modifier assignment logic exists. |
| 3.6 | Modifier Management | 🔲 Not implemented | No modifier weight/management system in admin. Scoring weights exist but are for base stats, not card modifiers. |
| 3.7 | View Seasonal Reserve Cards | ⚠️ Diverged | Bench shown in My Team tab with player name, rarity, and weekly points. No season-accumulated points per card shown. No filtering/sorting UI for bench cards. |
| 3.8 | View Permanent Collection | 🔲 Not implemented | Post-MVP; no cross-season collection. |
| 4.1 | Place Cards into Active Slots | ⚠️ Diverged | 5 active slots enforced; activate/deactivate endpoints work; single-player-per-roster rule enforced. However, there is no check preventing roster changes on a locked week — the activate/deactivate endpoints don't verify week lock status. |
| 4.2 | Lock Active Cards | ⚠️ Diverged | `auto_lock_weeks` runs at startup; weeks have `is_locked` flag. UI shows lock status and banner. However, there's no background scheduler to lock weeks at Sunday EoD during runtime — only at startup. |
| 4.3 | Admin Move Series Time Manually | 🔲 Not implemented | No endpoint to view or edit series timing. Schedule is read-only from Google Sheets. |
| 4.4 | Preserve Points | ✅ Aligned | `WeeklyRosterEntry` snapshots store locked-week rosters; points derived from `player_match_stats` scoped by week time range. Season total computed from all locked weeks. |
| 5.1 | Free Weekly Token | 🔲 Not implemented | No mechanism grants a token to all users when a week locks. `auto_lock_weeks` doesn't include token distribution. |
| 5.2 | Token Log | 🔲 Not implemented | No audit/log table for token events. Admin can see current balances but not grant history. |
| 5.3 | Spend Token to Draw Card | ⚠️ Diverged | 1 token deducted, card assigned, duplicate player avoidance implemented. However, higher-rarity duplicate exception is not implemented — once user owns all players, any card is allowed regardless of rarity comparison. |
| 5.4 | Redeem Code | ✅ Aligned | `/redeem` validates code, grants tokens, enforces one-use-per-user, records redemption with timestamp. |
| 5.5 | Generate Codes (Admin) | ✅ Aligned | `/codes` POST creates codes with configurable token amount; server-side admin validation. Codes are reusable across users. |
| 5.6 | View Token Balance | ✅ Aligned | Duplicate of 2.2; token balance visible in header. |
| 5.7 | Re-roll Modifiers | 🔲 Not implemented | No re-roll endpoint or UI. Card model lacks modifiers entirely. |
| 6.1 | Score Active Cards | ⚠️ Diverged | Scoring uses Dota 2 match data via `player_match_stats.fantasy_points`. Only locked-week snapshot cards score for that week. However, scoring is based on base player stats, not card-specific modifiers (which don't exist). |
| 6.2 | Configure Event Weights (Admin) | ⚠️ Diverged | Weights editable via `/weights/{key}` PUT. However, the endpoint lacks admin authentication — any user can update weights. No logging of weight changes. |
| 6.3 | Card Modifier Scoring | 🔲 Not implemented | No card modifier system exists; scoring is purely base stats × weights. |
| 6.4 | Track Season Points | ✅ Aligned | Season points computed from all locked weekly roster entries; visible in roster view and season leaderboard. |
| 6.5 | Track Points per Card | ⚠️ Diverged | Weekly points per card shown in roster view. However, historical per-card tracking across weeks is not directly surfaced — only the current/selected week's card points are shown. |
| 6.6 | Prevent Duplicate Scoring | ⚠️ Diverged | `player_match_stats` has unique match/player entries preventing duplicate stat rows. Ingestion idempotency depends on `ingest.py` (not shown). Points query scopes by week time range, but same match could theoretically span week boundaries. |
| 7.1 | Fetch Player Data | ❓ Ambiguous | `ingest.py` and `enrich.py` not provided. Player data exists in DB; likely fetched from OpenDota based on naming. Cannot verify validation/logging/retry. |
| 7.2 | Import Match Data | ❓ Ambiguous | `ingest_league()` called from multiple places. Match model stores `start_time`, `radiant_win`. Cannot verify implementation details without `ingest.py`. |
| 7.3 | Handle API Failures | ⚠️ Diverged | Auto-ingest wraps calls in try/except with print logging. No retry logic visible. No admin-facing failure visibility beyond console logs. |
| 8.1 | Season Leaderboard | ✅ Aligned | `/leaderboard/season` ranks users by total season points from locked weeks. |
| 8.2 | Scrollable Leaderboard | ✅ Aligned | Leaderboard is in a dedicated tab; standard HTML table is scrollable. |
| 8.3 | Show User Rank | ⚠️ Diverged | Current user's row is highlighted in gold in the leaderboard. However, the user's rank is not persistently visible outside the leaderboard tab (e.g., not in header or My Team). |
| 8.4 | Weekly Leaderboard | ✅ Aligned | `/leaderboard/weekly?week_id=` endpoint and week selector UI in leaderboard tab. |
| 9.1 | Generate Codes | ✅ Aligned | Duplicate of 5.5; covered above. |
| 9.2 | Grant Tokens | ✅ Aligned | `/grant-tokens` endpoint with admin check; UI in admin tab with per-user amount input. |
| 9.3 | Configure Scoring | ⚠️ Diverged | Duplicate of 6.2; weights endpoint lacks admin auth check. |
| 9.4 | Manage Season Lifecycle | 🔲 Not implemented | No endpoints for season start/end/reset management. |
| 9.5 | View System Status | ⚠️ Diverged | `/schedule/debug` provides limited diagnostics. No comprehensive system status dashboard (DB stats, ingest status, user counts, etc.). |
| 9.6 | Start New Season | 🔲 Not implemented | No new-season endpoint or workflow. |
| 10.1 | Explain Scoring | ✅ Aligned | "How is scoring calculated?" toggle in My Team tab explains the formula and stat-to-weight mapping. |
| 11.1 | Server-side Validation | ⚠️ Diverged | Registration, drawing, and code redemption have server-side validation. However, auth is localStorage-based with no server-side session/JWT — any request with a valid `user_id` integer is trusted. Weight updates lack admin checks. |
| 11.2 | Audit Logs | 🔲 Not implemented | No audit log table or mechanism. `CodeRedemption` tracks code usage with timestamp, but no general audit trail for token grants, draws, admin actions, re-rolls, or season resets. |
| 12.1 | Player Browser | ✅ Aligned | Players tab with search, stats columns, clickable player modal with full match history. |
| 12.2 | Team Browser | ✅ Aligned | Teams tab with match/player counts; team modal shows roster. |
| 12.3 | Schedule Tab | ✅ Aligned | Schedule tab shows full season schedule; team names are clickable links to team modal. |
| 12.4 | User Profile Tab | ✅ Aligned | Profile tab allows editing display name and linking OpenDota player ID. |
| 12.5 | Week History Selector | ✅ Aligned | `rosterWeekSelect` dropdown on My Team tab; past locked weeks show snapshot roster and earned points. |
| 12.6 | Auto-ingest on Startup | ✅ Aligned | `AUTO_INGEST_LEAGUES` env var parsed at startup; leagues ingested in background thread; existing data skipped (assumed via `ingest.py`). |
| 12.7 | Admin: Recalculate Points | ✅ Aligned | `/recalculate` endpoint recalculates all `fantasy_points` using current weights; admin-gated. |
| 12.8 | Admin: Manual League Ingestion | ✅ Aligned | `/ingest/league/{league_id}` endpoint with admin check; UI in admin tab. |
| 12.9 | Admin: Schedule Refresh | ✅ Aligned | `/schedule/refresh` busts cache and re-fetches from Google Sheets; admin-gated. |
| 12.10 | Admin: Grant Draws to User | ⚠️ Diverged | `/grant-tokens` grants tokens (which can be used for draws), but there is no separate "grant draws" concept. The implementation effectively covers this since tokens = draws, but the naming and semantics differ. |

## Key divergences

1. **No server-side authentication/session management (1.2, 1.5, 11.1)**: All auth relies on client-side localStorage `user_id`; any API caller can impersonate any user by sending a different `user_id`. — **Update implementation** (add JWT or session tokens).

2. **Card modifiers entirely absent (3.5, 3.6, 5.7, 6.3)**: The Card model has no modifier fields; no modifier assignment, re-roll, or modifier-based scoring exists. This affects four stories. — **Update implementation** (add modifier system to model, drawing, and scoring).

3. **Forgot/temporary password flow missing (1.3)**: No email sending capability or temporary password endpoint exists. — **Update implementation** or **clarify story** if deferring to post-MVP.

4. **Weight update endpoint lacks admin authentication (6.2, 9.3)**: `PUT /weights/{key}` has no `require_admin` check — any user can modify scoring weights. — **Update implementation** (add admin guard).

5. **Free weekly token grant not implemented (5.1)**: No mechanism distributes a token to all users when a week locks; `auto_lock_weeks` only sets `is_locked`. — **Update implementation**.

6. **Audit log system absent (11.2, 5.2)**: No general audit log table. Only `CodeRedemption` tracks one event type. Token grants, draws, admin actions, and season resets are unlogged. — **Update implementation**.

7. **Roster changes not blocked on locked weeks (4.1, 4.2)**: The `/roster/{card_id}/activate` and `/deactivate` endpoints don't check whether the current week is locked, allowing roster edits after lock. — **Update implementation** (check week lock before allowing changes).

8. **Season lifecycle management missing (9.4, 9.6)**: No endpoints or UI for starting/ending/resetting seasons. Weeks are auto-generated but there's no admin control over season boundaries. — **Update implementation** or **clarify story** for MVP scope.

9. **Login error message doesn't match spec (1.2)**: Backend returns "Invalid username or password" but story requires "Login failed – Invalid credentials." — **Update implementation** (change error string).

10. **Higher-rarity duplicate draw exception not implemented (5.3)**: When a user owns all players, the fallback allows any card regardless of rarity. The spec requires higher-rarity duplicates to be allowed as an explicit exception path. — **Clarify story** (define exact rarity upgrade rules) and **update implementation**.
