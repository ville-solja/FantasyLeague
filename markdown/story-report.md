<!-- Generated automatically by scripts/story_report.py — do not edit by hand -->
_Last updated: 2026-03-30 11:51 UTC_

# Story Coverage Report

| ID | Story | Status | Notes |
|----|-------|--------|-------|
| 1.1 | User Registration | ✅ Aligned | `/register` endpoint validates unique username/email, creates user, grants initial tokens, records `created_at` timestamp. |
| 1.2 | User Login | ⚠️ Diverged | `/login` works with username+password and returns user data, but there is no real session/token management (no JWT, no cookie); auth state is purely client-side `localStorage`. Logged-out users can still call authenticated endpoints if they know a `user_id`. Error message says "Invalid username or password" not the specified "Login failed – Invalid credentials." |
| 1.3 | User Receive Temporary Password | 🔲 Not implemented | No forgot-password or temporary-password flow exists anywhere in the codebase. |
| 1.4 | User Password Reset | ⚠️ Diverged | Profile page has a change-password flow (`PUT /profile/password`) but it requires the current password — this is a "change" not a "reset" for users who forgot their password. Meets the AC as written ("flow for setting a new password") but only when the user knows their current password. |
| 1.5 | User Logout | ⚠️ Diverged | Client-side logout clears `localStorage` and calls `applyAuthState()`, which redirects to `switchTab("leaderboard")`. However, there is no server-side session invalidation because no server sessions exist. The leaderboard tab is visible without login as required. |
| 1.6 | Admin-only Access | ✅ Aligned | `require_admin()` helper checks `is_admin` flag; admin tab is hidden for non-admin users in the frontend; admin endpoints reject non-admin `user_id`. |
| 2.1 | Grant Starter Tokens on Registration | ✅ Aligned | `INITIAL_TOKENS` (default 5) granted at registration via `User(tokens=INITIAL_TOKENS)`. |
| 2.2 | Token Visibility | ✅ Aligned | `tokenBalance` element is displayed in the header across all tabs; updated on login, draw, redeem, and roster load. |
| 2.3 | View Cards | ⚠️ Diverged | Cards show player name, rarity (`card_type`), and points, but **modifiers are not implemented** — Card model has no modifier fields, so "quality and modifiers" cannot be displayed. Cards are shown in "My Team" tab as required. |
| 2.4 | View Weekly Rosters | ⚠️ Diverged | Upcoming week's roster is the default view. Carryover from previous week is **not implemented** — if a user doesn't set a roster, it starts empty. Lock timing is shown in UI but is based on `start_time` of the week, not explicitly "every Sunday at end of day." |
| 2.5 | View Current and Season Points | ✅ Aligned | Weekly and season points are both displayed in the roster view. Points are 0 for new users. Week history selector allows viewing past weeks. |
| 2.6 | View Collection | 🔲 Not implemented | Post-MVP; no separate Collection tab exists. |
| 3.1 | Generate Cards | ⚠️ Diverged | `seed_cards(league_id)` generates cards, and admin can ingest leagues. However, the card distribution per player (1 golden/2 purple/4 blue/8 white) cannot be verified from the shown code — `seed.py` is not provided. Card types in the model are "common/rare/epic/legendary" not "golden/purple/blue/white". Admin can ingest by league ID but no manual player ID list import is visible. |
| 3.2 | Card Drawing | ✅ Aligned | `/draw` deducts a token, assigns the card to the user, places it in active roster if slots available or bench otherwise, and returns card data shown via reveal modal. |
| 3.3 | Remove Cards from Pool | 🔲 Not implemented | Post-MVP; no endpoint or UI for removing players/cards from the pool. |
| 3.4 | Assign Randomized Card Rarity | ⚠️ Diverged | Cards have a `card_type` (rarity) but rarity is assigned at card generation time in `seed_cards()` (not shown), not at draw time. The draw picks randomly from the unclaimed pool, so rarity is predetermined. Meets the spirit but "randomized" assignment timing differs. |
| 3.5 | Assign Randomized Modifiers | 🔲 Not implemented | The `Card` model has no modifier columns. No modifier assignment logic exists. |
| 3.6 | Modifier Management | 🔲 Not implemented | No modifier system exists; the `Weight` table manages scoring weights, not card modifiers. |
| 3.7 | View Seasonal Reserve Cards | ⚠️ Diverged | Bench cards are shown in My Team tab with player, rarity, and weekly points. However, **season-accumulated points per card** are not shown (only week-scoped points). No filtering/sorting of bench cards is implemented. |
| 3.8 | View Permanent Collection | 🔲 Not implemented | Post-MVP. |
| 4.1 | Place Cards into Active Slots | ⚠️ Diverged | Activate/deactivate endpoints exist with 5-slot limit and single-player-per-roster rule. However, there is **no lock check** — users can activate/deactivate cards even when the current week is locked. The lock only affects the UI (buttons hidden), not the server. |
| 4.2 | Lock Active Cards | ⚠️ Diverged | `auto_lock_weeks()` is called at startup but there's no recurring scheduler — if the server doesn't restart, weeks won't auto-lock. UI shows lock status and upcoming lock date. The lock banner is shown for locked weeks. |
| 4.3 | Admin Move Series Time Manually | 🔲 Not implemented | No endpoint or UI for manually adjusting series/match timing. Schedule data comes from Google Sheets and there's no override mechanism. |
| 4.4 | Preserve Points | ✅ Aligned | `WeeklyRosterEntry` snapshots persist per week; season points are derived by summing across locked weekly entries. |
| 5.1 | Free Weekly Token | 🔲 Not implemented | No logic grants a free token when a week locks. `auto_lock_weeks()` only sets `is_locked = True`. |
| 5.2 | Token Log | 🔲 Not implemented | No audit/log table for token events. Admin can see current balances but not grant history or event log. |
| 5.3 | Spend Token to Draw Card | ⚠️ Diverged | Token is deducted and card is assigned. Duplicate-player avoidance is implemented (prefers unowned players, falls back to any). However, the AC says "higher-rarity duplicates are allowed" as an exception — current code allows **any** duplicate when all players are owned, not specifically higher-rarity ones. |
| 5.4 | Redeem Code | ✅ Aligned | `/redeem` validates code, enforces one-use-per-user, grants tokens, shows error for invalid codes. Redemptions are logged in `code_redemptions` table with timestamp. |
| 5.5 | Generate Codes (Admin) | ✅ Aligned | `/codes` POST creates codes with configurable token amount; server-side validation; admin-only. Duplicate of 9.1. |
| 5.6 | View Token Balance | ✅ Aligned | Duplicate of 2.2; token balance shown in header. |
| 5.7 | Re-roll Modifiers | 🔲 Not implemented | No re-roll endpoint or UI. Modifiers don't exist on cards. |
| 6.1 | Score Active Cards | ⚠️ Diverged | Scoring uses Dota 2 match data and `player_match_stats.fantasy_points`. However, scoring is based on **player_id** from weekly roster snapshot cards, not on whether cards were locked/active at the time of scoring. The `WeeklyRosterEntry` snapshot mechanism handles the "only active cards score" requirement, but snapshot creation logic (in `weeks.py`, not shown) is uncertain. |
| 6.2 | Configure Event Weights (Admin) | ⚠️ Diverged | Weights are adjustable via admin UI. However, there is **no admin auth check** on `PUT /weights/{key}` — anyone can update weights. No logging of weight changes. "Only affects future scoring" is handled by recalculate being a separate manual action. |
| 6.3 | Card Modifier Scoring | 🔲 Not implemented | No card modifier system; scoring is purely from base stat weights. |
| 6.4 | Track Season Points | ✅ Aligned | Season points are computed from all locked weekly roster entries and displayed to the user. |
| 6.5 | Track Points per Card | ⚠️ Diverged | Weekly points per card are shown in the roster view. However, there's no historical per-card tracking across multiple weeks — you can view each week separately but not a card's cumulative history. |
| 6.6 | Prevent Duplicate Scoring | ⚠️ Diverged | `player_match_stats` uses composite player_id + match_id but there's no unique constraint in the model. The `ingest_league` function (not shown) presumably handles dedup. The query scopes by `match.start_time BETWEEN week.start_time AND week.end_time`, which prevents cross-week double counting. |
| 7.1 | Fetch Player Data | ❓ Ambiguous | `ingest.py` and `enrich.py` are not provided; existence of the import flow is confirmed by references but details can't be verified. |
| 7.2 | Import Match Data | ❓ Ambiguous | Same as 7.1 — `ingest_league()` is called but implementation not shown. |
| 7.3 | Handle API Failures | ⚠️ Diverged | Auto-ingest has a try/except that catches and logs failures, but there's no retry logic, no admin visibility into failures beyond console logs. |
| 8.1 | Season Leaderboard | ✅ Aligned | `/leaderboard/season` ranks all users by total season points from locked weekly roster entries. |
| 8.2 | Scrollable Leaderboard | ✅ Aligned | Leaderboard is in a separate tab and renders in a standard table (scrollable via browser). |
| 8.3 | Show User Rank | ⚠️ Diverged | The logged-in user's row is highlighted in gold on the leaderboard, but their rank is **not persistently visible** across other tabs — only shown when viewing the leaderboard tab. |
| 8.4 | Weekly Leaderboard | ✅ Aligned | `/leaderboard/weekly?week_id=` endpoint and week selector in the UI provide weekly rankings. |
| 9.1 | Generate Codes | ✅ Aligned | Duplicate of 5.5; covered above. |
| 9.2 | Grant Tokens | ✅ Aligned | `/grant-tokens` endpoint allows admin to grant tokens to a specific user with amount validation. |
| 9.3 | Configure Scoring | ⚠️ Diverged | Duplicate of 6.2; weights endpoint lacks admin auth check. |
| 9.4 | Manage Season Lifecycle | 🔲 Not implemented | No endpoint or UI for managing season state (start, end, archive). Weeks are auto-generated but seasons are not explicitly modeled. |
| 9.5 | View System Status | 🔲 Not implemented | No system status dashboard. `/schedule/debug` exists but is limited to schedule sheet connectivity. |
| 9.6 | Start New Season | 🔲 Not implemented | No new-season endpoint or flow. |
| 10.1 | Explain Scoring | ✅ Aligned | "How is scoring calculated?" toggle in the My Team tab explains the formula and weight names. |
| 11.1 | Server-side Validation | ⚠️ Diverged | Most actions have server-side checks (token balance, ownership, admin), but key gaps: `PUT /weights/{key}` has **no auth check**; activate/deactivate cards have **no week-lock check** server-side; auth is `user_id`-based with no session tokens, so any user_id can be spoofed. |
| 11.2 | Audit Logs | 🔲 Not implemented | No audit log table or mechanism. `CodeRedemption` tracks code usage with timestamps, but there are no logs for registration rewards, token grants, draws, re-rolls, admin actions, or season resets. |
| 12.1 | Player Browser | ✅ Aligned | Players tab with search, stats columns, and detail modal with full match history. |
| 12.2 | Team Browser | ✅ Aligned | Teams tab with match/player counts; detail modal shows current roster. |
| 12.3 | Schedule Tab | ✅ Aligned | Schedule tab shows full season schedule with clickable team names linking to team modal. |
| 12.4 | User Profile Tab | ✅ Aligned | Profile tab allows editing display name and linking OpenDota player ID. |
| 12.5 | Week History Selector | ✅ Aligned | Dropdown on My Team tab allows viewing past locked weeks' snapshots and points. |
| 12.6 | Auto-ingest on Startup | ✅ Aligned | `AUTO_INGEST_LEAGUES` env var triggers background ingestion on server start; skips existing data. |
| 12.7 | Admin: Recalculate Points | ✅ Aligned | `/recalculate` endpoint recomputes all `fantasy_points` using current weights. |
| 12.8 | Admin: Manual League Ingestion | ✅ Aligned | `/ingest/league/{league_id}` with admin check available in admin tab. |
| 12.9 | Admin: Schedule Refresh | ✅ Aligned | `/schedule/refresh` busts cache and re-fetches from Google Sheets source. |
| 12.10 | Admin: Grant Draws to User | ⚠️ Diverged | Admin can grant **tokens** (not "draws") to users. The concept is equivalent since 1 token = 1 draw, but there's no separate "draw limit" concept — it's purely token-based. |

## Key divergences

1. **No server-side authentication/sessions (1.2, 11.1):** Auth relies entirely on client-side `localStorage` of `user_id`; any API caller can impersonate any user by supplying their numeric ID. — *Update implementation* (add JWT or session tokens).

2. **Card modifiers not implemented (3.5, 3.6, 5.7, 6.3):** The Card model has no modifier fields; modifier assignment, management, re-rolling, and modifier-based scoring are entirely absent. — *Update implementation* or *clarify story* to defer modifiers to a later phase.

3. **No "forgot password" / temporary password flow (1.3):** No endpoint or UI for sending a temporary password via email. — *Update implementation* or *clarify story* to mark as post-MVP.

4. **No free weekly token grant (5.1):** `auto_lock_weeks()` locks weeks but does not distribute tokens to users. — *Update implementation*.

5. **No audit log system (5.2, 11.2):** Token grants, draws, admin actions, and other events are not logged in any audit table. Only code redemptions have a dedicated tracking table. — *Update implementation*.

6. **Weight update endpoint lacks admin auth (6.2, 9.3):** `PUT /weights/{key}` has no `require_admin()` call, allowing any user to modify scoring weights. — *Update implementation*.

7. **Roster activate/deactivate not enforced server-side during lock (4.1, 4.2):** The server does not check if the current week is locked before allowing card activation/deactivation; the lock is only enforced in the UI by hiding buttons. — *Update implementation*.

8. **No roster carryover between weeks (2.4):** When a new week begins, there is no logic to copy the previous week's active roster to the upcoming week. Users start with whatever `is_active` flags exist on their cards. — *Clarify story* (is carryover expected on the card level or snapshot level?) then *update implementation*.

9. **No season lifecycle management (9.4, 9.6):** There are no endpoints for starting, ending, or arch
