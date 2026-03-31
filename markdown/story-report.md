<!-- Generated automatically by scripts/story_report.py — do not edit by hand -->
_Last updated: 2026-03-31 12:15 UTC_

# Story Coverage Report

| ID | Story | Status | Notes |
|----|-------|--------|-------|
| 1.1 | User Registration | ✅ Aligned | `/register` endpoint validates unique username/email, creates user, grants initial tokens, records `created_at` timestamp, and logs via audit. |
| 1.2 | User Login | ⚠️ Diverged | Login works with username+password and returns session. However, logged-out users can still access several GET endpoints (`/players`, `/roster/{id}`, `/leaderboard`, etc.) without authentication — only `/draw`, `/roster/activate`, `/roster/deactivate`, profile writes, and admin routes are protected. |
| 1.3 | User Receive Temporary Password | 🔲 Not implemented | No forgot-password or temporary-password-via-email flow exists anywhere in the codebase. |
| 1.4 | User Password Reset | ✅ Aligned | `PUT /profile/password` requires current password and sets a new one. Available on the Profile tab. |
| 1.5 | User Logout | ⚠️ Diverged | Logout clears session and works from any page. However, after logout the frontend calls `applyAuthState()` which switches to the `leaderboard` tab — but doesn't explicitly redirect; if the user was on another tab, that tab simply hides. Story says redirect to leaderboard (only visible tab), which functionally happens. Minor: the leaderboard tab is not the *only* visible tab — Players, Teams, and Schedule tabs remain visible to logged-out users. |
| 1.6 | Admin-only Access | ✅ Aligned | Admin tab hidden for non-admins via `applyAuthState()`. All admin endpoints use `require_admin` dependency. Admin flag is set per user record. |
| 2.1 | Grant Starter Tokens on Registration | ✅ Aligned | `INITIAL_TOKENS` (default 5) granted at registration via `User(tokens=INITIAL_TOKENS)`. |
| 2.2 | Token Visibility | ⚠️ Diverged | Token balance is shown in the header (`#tokenBalance`) and on the My Team tab (`#drawCounter`). It is *not* visible on the Players, Teams, Schedule, or Leaderboard tabs when those are active — the element exists in header but is only updated on roster/draw actions, not guaranteed refreshed across all tab switches. |
| 2.3 | View Cards | ✅ Aligned | Drawn cards show player name, rarity (card_type), avatar, and team. Cards appear in active roster or bench on the My Team tab. Modifiers are not displayed because the Card model has no modifier fields (see 3.5). |
| 2.4 | View Weekly Rosters | ⚠️ Diverged | Upcoming week is the default view (via `get_next_editable_week`). Lock timing is shown in UI. However, the story says "all active slots should be initially carried over from the previous week" — the snapshot mechanism in `weeks.py` (not shown but referenced via `auto_lock_weeks`) is unclear; the live roster uses `is_active` on cards rather than copying slots per-week, so there's implicit carry-over but not an explicit weekly copy. Lock time is described as "every Sunday at end of day" in the story; code uses `auto_lock_weeks` whose logic isn't visible here. |
| 2.5 | View Current and Season Points | ✅ Aligned | Weekly points and season total both displayed in roster view. New users show 0. Week history selector allows viewing past weeks' points. |
| 2.6 | View Collection | 🔲 Not implemented | Marked post-MVP. No separate Collection tab exists. |
| 3.1 | Generate Cards | ⚠️ Diverged | Admin can ingest a league ID which generates cards via `seed_cards(league_id)`. The story specifies per-player distribution of 1 golden / 2 purple / 4 blue / 8 white; the code uses card_type values `common/rare/epic/legendary` — naming differs (golden≠legendary? purple≠epic?). The actual distribution is in `seed.py` (not shown) so exact counts can't be confirmed. No explicit "import by player ID list" endpoint exists — only league-based ingestion. |
| 3.2 | Card Drawing | ✅ Aligned | `/draw` deducts a token, assigns card to user, places in active roster if slots available otherwise bench. Card details shown to user immediately via reveal modal. |
| 3.3 | Remove Cards from Pool | 🔲 Not implemented | Marked post-MVP. No endpoint or UI to remove a player's cards and refund tokens. |
| 3.4 | Assign Randomized Card Rarity | ⚠️ Diverged | Cards have a `card_type` (rarity) set at generation time in `seed_cards`. Story says "randomized" but the generation appears to create fixed counts per rarity tier per player (deterministic distribution, not random assignment at draw time). |
| 3.5 | Assign Randomized Modifiers | 🔲 Not implemented | The `Card` model has no modifier column(s). No modifier generation or storage exists. Cards only have `card_type` (rarity). |
| 3.6 | Modifier Management | 🔲 Not implemented | No modifier system exists to manage. Rarity weights exist but are not the same as card modifiers. |
| 3.7 | View Seasonal Reserve Cards | ⚠️ Diverged | Bench cards shown on My Team tab with player name, rarity, and weekly points. However, "points accumulated over the season" per card is not shown — only current week points are displayed. No filtering/sorting of bench cards is implemented. |
| 3.8 | View Permanent Collection | 🔲 Not implemented | Marked post-MVP. No cross-season collection system. |
| 4.1 | Place Cards into Active Slots | ⚠️ Diverged | 5-slot roster with activate/deactivate works. Duplicate player check exists. However, cards lock based on week locking, and the lock/unlock is tied to `is_active` on the card globally — not per-week. The activate/deactivate endpoints don't check whether the current week is locked; the UI hides the buttons but server doesn't enforce it. |
| 4.2 | Lock Active Cards | ⚠️ Diverged | Auto-lock happens via `auto_lock_weeks` (logic in `weeks.py`, not shown). UI shows lock status and a banner. Story says "Sunday EoD" — the actual lock timing depends on `weeks.py` implementation. The "informed of upcoming lock" requirement is met via the `rosterWeekStatus` element showing lock date. |
| 4.3 | Admin Move Series Time Manually | 🔲 Not implemented | No endpoint or UI to view series or reassign match dates. Schedule shows series but has no edit capability. |
| 4.4 | Preserve Points | ✅ Aligned | Points derived from `player_match_stats.fantasy_points` stored in DB. Weekly roster snapshots (`weekly_roster_entries`) preserve which cards were active per week. Season total is computed from locked weeks. |
| 5.1 | Free Weekly Token | 🔲 Not implemented | No mechanism found that grants a free token to all users when a week locks. `auto_lock_weeks` logic is not shown but no token-granting code is visible in `main.py`. |
| 5.2 | Token Log | ⚠️ Diverged | Audit log captures token draws, redemptions, and admin grants with timestamps and actor info. However, weekly free token grants (not implemented) aren't logged, and there's no dedicated "token log" view — it's mixed into the general audit log. The story asks for "total number of users affected" for weekly grants which doesn't exist. |
| 5.3 | Spend Token to Draw Card | ⚠️ Diverged | Token deducted, card assigned, duplicate player avoidance implemented. However, the story says "higher-rarity duplicates are allowed" as an exception — the code falls back to allowing *any* duplicate (including same or lower rarity) when user owns all players, not specifically higher-rarity ones. |
| 5.4 | Redeem Code | ✅ Aligned | `/redeem` validates code, checks one-use-per-user, grants tokens, logs redemption. Invalid code returns error. |
| 5.5 | Generate Codes (Admin) | ✅ Aligned | `POST /codes` creates codes with configurable token amount. Server-side validation present. Codes are reusable across users (one use per user). |
| 5.6 | View Token Balance | ✅ Aligned | Duplicate of 2.2. Token balance visible in header. |
| 5.7 | Re-roll Modifiers | 🔲 Not implemented | No re-roll endpoint exists. No modifier system exists on cards. |
| 6.1 | Score Active Cards | ⚠️ Diverged | Scoring uses Dota 2 match data via `fantasy_score`. Points are scoped to locked weeks via `weekly_roster_entries`. However, scoring appears to count *all* matches a player participated in during the week window — not only matches where the card was "locked active." The rarity multiplier is applied at query time, not stored. |
| 6.2 | Configure Event Weights (Admin) | ✅ Aligned | Weights adjustable via `PUT /weights/{key}`. Recalculate is a separate action so changes can be forward-only. Audit logged. |
| 6.3 | Card Modifier Scoring | 🔲 Not implemented | No card modifier system exists. Only rarity multiplier is applied. |
| 6.4 | Track Season Points | ✅ Aligned | Season points computed from all locked weeks' roster entries. Visible on My Team tab and season leaderboard. |
| 6.5 | Track Points per Card | ⚠️ Diverged | Weekly points per card visible in roster view for the selected week. However, there's no dedicated "historical tracking" UI showing a card's point contribution across all weeks — only the current/selected week's contribution is shown. |
| 6.6 | Prevent Duplicate Scoring | ⚠️ Diverged | `player_match_stats` has composite data (player_id + match_id) and ingestion (in `ingest.py`, not shown) presumably avoids duplicates. The recalculate endpoint is noted as safe to re-run. However, there's no explicit unique constraint on (player_id, match_id) in the model — only `id` is primary key. |
| 7.1 | Fetch Player Data | ❓ Ambiguous | `ingest.py` and `enrich.py` are referenced but not included in the codebase provided. Cannot verify API call patterns, validation, or error handling. |
| 7.2 | Import Match Data | ❓ Ambiguous | Same as 7.1 — `ingest_league` is called but implementation not provided. |
| 7.3 | Handle API Failures | ⚠️ Diverged | Auto-ingest wraps calls in try/except and prints errors but continues. No retry logic is visible in `main.py`. The actual retry/failure handling in `ingest.py` cannot be verified. |
| 8.1 | Season Leaderboard | ✅ Aligned | `/leaderboard/season` ranks all users by total season points with rarity multipliers applied. |
| 8.2 | Scrollable Leaderboard | ✅ Aligned | Leaderboard is in a separate tab. Standard HTML table with browser scroll. |
| 8.3 | Show User Rank | ⚠️ Diverged | The logged-in user's row is highlighted (gold color, bold) in the leaderboard table. However, if the user is far down the list, they must scroll to find themselves — there's no persistent "Your rank: #X" indicator always visible. |
| 8.4 | Weekly Leaderboard | ✅ Aligned | `/leaderboard/weekly?week_id=` returns per-week rankings. UI toggle between Season and Weekly with week selector. |
| 9.1 | Generate Codes | ✅ Aligned | Duplicate of 5.5. Covered above. |
| 9.2 | Grant Tokens | ✅ Aligned | `POST /grant-tokens` allows admin to grant tokens to specific users. Audit logged. |
| 9.3 | Configure Scoring | ✅ Aligned | Duplicate of 6.2. Covered above. |
| 9.4 | Manage Season Lifecycle | ⚠️ Diverged | Weeks are auto-generated via `generate_weeks`. `auto_lock_weeks` handles locking. However, there's no explicit UI for managing season start/end, pausing a season, or archiving. The lifecycle is implicit. |
| 9.5 | View System Status | ⚠️ Diverged | Admin tab shows users, weights, codes, audit logs, and has a schedule debug endpoint. However, there's no dedicated "system status" dashboard showing e.g. last ingestion time, DB health, current season state, or API connectivity status. |
| 9.6 | Start New Season | 🔲 Not implemented | No endpoint or UI to start a new season, reset standings, or archive the current season. |
| 10.1 | Explain Scoring | ✅ Aligned | "How is scoring calculated?" toggle on My Team tab explains the formula and mentions admin-configurable weights. |
| 11.1 | Server-side Validation | ✅ Aligned | Auth checks on protected endpoints, input validation (empty strings, min amounts, duplicates), ownership checks on card operations. Activate/deactivate don't server-side check week lock status (see 4.1). |
| 11.2 | Audit Logs | ⚠️ Diverged | Tracks: registrations, logins, token draws, redemptions, admin actions (ingest, weight update, grant tokens, code CRUD, recalculate, schedule refresh). All include timestamp and actor. However, card activate/deactivate actions are *not* audited. Token balance changes from draws are logged but the detail focuses on the card, not the token deduction itself. |
| 12.1 | Player Browser | ✅ Aligned | Players tab with search, match count, avg/total points. Detail modal with full match history. |
| 12.2 | Team Browser | ✅ Aligned | Teams tab with match/player counts. Detail modal with roster. |
| 12.3 | Schedule Tab | ✅ Aligned | Full schedule with upcoming/past series, team links, stream links. |
| 12.4 | User Profile Tab | ✅ Aligned | Username editing and OpenDota player ID linking on Profile tab. |
| 12.5 | Week History Selector | ✅ Aligned | Dropdown on My Team tab for selecting past weeks with snapshot roster and points. |
| 12.6 | Auto-ingest on Startup | ✅ Aligned | `AUTO_INGEST_LEAGUES` env var parsed at startup; ingestion runs in background thread executor. |
| 12.7 | Admin: Recalculate Points | ✅ Aligned | `POST /recalculate` recalculates all `fantasy_points` using current weights. |
| 12.8 | Admin: Manual League Ingestion | ✅ Aligned | `POST /ingest/league/{league_id}` with admin auth. |
| 12.9 | Admin: Schedule Refresh | ✅ Aligned | `POST /schedule/refresh` busts cache and re-fetches from Google Sheets. |
| 12.10 | Admin: Grant Draws to User | ⚠️ Diverged | The grant-tokens endpoint grants *tokens* (which can be spent on draws), but the story title says "Grant Draws" implying a separate draw-limit mechanism. The old `draw_limit` column was migrated to `tokens`, so this is effectively the same thing now. Story should be updated to reflect the token-based system. |

## Key divergences

1. **1.3 — Temporary password / forgot-password flow is entirely missing.** No email-sending capability exists in the codebase. — *Update implementation* or *descope story*.

2. **3.5 / 3.6 / 5.7 / 6.3 — The entire card modifier system is unimplemented.** Cards have only rarity (`card_type`), no per-card modifiers, no re-roll, and no modifier-based scoring bonuses. — *Update implementation* (significant feature gap).

3. **4.1 — Activate/deactivate endpoints don't enforce week lock server-side.** The
