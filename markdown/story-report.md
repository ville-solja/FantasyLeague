<!-- Generated automatically by scripts/story_report.py — do not edit by hand -->
_Last updated: 2026-03-30 11:45 UTC_

# Story Coverage Report

| ID | Story | Status | Notes |
|----|-------|--------|-------|
| 1.1 | User Registration | ✅ Aligned | `/register` endpoint checks unique username/email, creates account, grants initial tokens, records `created_at` timestamp. |
| 1.2 | User Login | ⚠️ Diverged | `/login` validates credentials and returns user data, but there is no server-side session management — auth state is stored only in `localStorage`. Logged-out users can call authenticated endpoints by passing any `user_id`. Error message says "Invalid username or password" not "Login failed – Invalid credentials." |
| 1.3 | User Receive Temporary Password | 🔲 Not implemented | No forgot-password or temporary-password flow exists; no email sending capability. |
| 1.4 | User Password Reset | ✅ Aligned | `/profile/password` endpoint allows changing password when logged in; Profile tab has current/new password fields. |
| 1.5 | User Logout | ⚠️ Diverged | Client-side `logout()` clears `localStorage` and calls `applyAuthState()`, but no server-side session is invalidated (none exists). After logout the UI calls `switchTab("leaderboard")` which aligns with the story. |
| 1.6 | Admin-only Access | ⚠️ Diverged | Admin tab is hidden for non-admins in UI; `require_admin` checks on backend. However, some admin endpoints (e.g. `PUT /weights/{key}`) do not call `require_admin` — anyone can update scoring weights. |
| 2.1 | Grant Starter Tokens on Registration | ✅ Aligned | `INITIAL_TOKENS` (default 5) granted at registration. The value of N is configurable via env var. |
| 2.2 | Token Visibility | ✅ Aligned | `#tokenBalance` element displayed across all tabs in the header when logged in; updated on draw, redeem, and roster load. |
| 2.3 | View Cards | ⚠️ Diverged | Drawn cards are shown in My Team tab with player name, rarity (`card_type`), and team. However, cards have no modifiers — the Card model lacks modifier fields entirely, so "modifiers" cannot be displayed. |
| 2.4 | View Weekly Rosters | ⚠️ Diverged | Upcoming week's roster is the default view. Week selector exists. Lock timing is displayed. However, there is no automatic carry-over of the previous week's roster to the next week — the story requires this to limit the effect of missed roster updates. |
| 2.5 | View Current and Season Points | ✅ Aligned | Weekly and season points both shown on My Team tab; past weeks viewable via week selector; new users with no data see 0. |
| 2.6 | View Collection | 🔲 Not implemented | Post-MVP; no separate Collection tab exists. |
| 3.1 | Generate Cards | ⚠️ Diverged | `seed_cards` generates cards per player with 4 rarity tiers. Admin can trigger via league ingestion. However, the story specifies 1 golden/2 purple/4 blue/8 white — the code uses common/rare/epic/legendary with counts 8/4/2/1 which maps inversely. Card type names differ from story spec. Cannot confirm duplicate-avoidance in permanent pool without seeing `seed_cards`. |
| 3.2 | Card Drawing | ⚠️ Diverged | User can draw; card shown immediately; auto-placed in active or bench. But the story says card goes to bench if no empty active slots — the code does this. The draw deduplication logic prefers unowned players but falls back to any card (including same-rarity duplicates of owned players), which partially conflicts with 5.3's "no same-player unless all owned, exception: higher-rarity." |
| 3.3 | Remove Cards from Pool | 🔲 Not implemented | Post-MVP; no endpoint for removing players/cards from pool or refunding tokens. |
| 3.4 | Assign Randomized Card Rarity | ⚠️ Diverged | Rarity is assigned at card generation time (pre-seeded per player), not randomized at draw time. The draw picks randomly from the pool, so the user gets a random rarity indirectly. |
| 3.5 | Assign Randomized Modifiers | 🔲 Not implemented | The Card model has no modifier columns. No modifiers are generated or stored. |
| 3.6 | Modifier Management | 🔲 Not implemented | No modifier system exists; admin cannot adjust modifier weights. Scoring weights exist but are separate from card modifiers. |
| 3.7 | View Seasonal Reserve Cards | ⚠️ Diverged | Bench cards shown in My Team tab with player, rarity, and weekly points. No filtering/sorting UI is provided. Season-accumulated points per card are not shown (only weekly points). |
| 3.8 | View Permanent Collection | 🔲 Not implemented | Post-MVP; no cross-season collection. |
| 4.1 | Place Cards into Active Slots | ⚠️ Diverged | 5 active slots enforced; activate/deactivate endpoints exist; single-player-per-roster rule enforced. However, there is no check that the current week is unlocked — a user can activate/deactivate cards even when the roster should be locked. |
| 4.2 | Lock Active Cards | ⚠️ Diverged | `auto_lock_weeks` is called at startup, and weeks have `is_locked` field. The UI shows lock status and hides bench buttons for locked weeks. But there is no scheduled job to auto-lock on Sunday EoD — locking only happens at server restart. Activate/deactivate endpoints don't enforce lock. |
| 4.3 | Admin Move Series Time Manually | 🔲 Not implemented | No endpoint to view/edit series timing. Schedule data comes from external Google Sheet; no admin correction mechanism. |
| 4.4 | Preserve Points | ✅ Aligned | `WeeklyRosterEntry` snapshots store locked rosters; points derived from `player_match_stats` scoped to week time ranges; season total computed from all locked weeks. |
| 5.1 | Free Weekly Token | 🔲 Not implemented | No mechanism to grant all users a free token when a week locks. |
| 5.2 | Token Log | 🔲 Not implemented | No audit/log table for token grants, draws, or other token-related events. Admin can see current balances but not history. |
| 5.3 | Spend Token to Draw Card | ⚠️ Diverged | 1 token deducted on draw; card assigned. Dedup prefers unowned players but allows any duplicate when all players owned — story says higher-rarity duplicates are the only exception. No rarity comparison is done. |
| 5.4 | Redeem Code | ✅ Aligned | `/redeem` validates code, one-use-per-user enforced, tokens granted, `CodeRedemption` with timestamp stored. Invalid code returns error. |
| 5.5 | Generate Codes (Admin) | ✅ Aligned | `/codes` POST creates reusable codes with configurable token amount; server-side validation present. |
| 5.6 | View Token Balance | ✅ Aligned | Duplicate of 2.2; covered by header token display. |
| 5.7 | Re-roll Modifiers | 🔲 Not implemented | No re-roll endpoint; no modifier system to re-roll against. |
| 6.1 | Score Active Cards | ⚠️ Diverged | Scoring uses Dota 2 match data via `player_match_stats.fantasy_points`. Points are scoped to locked roster entries. However, scoring is based purely on player match stats with no card-specific modifier bonuses. Double-counting prevention relies on unique match_id in `player_match_stats` — not explicitly deduplicated at ingestion (would need to inspect `ingest.py`). |
| 6.2 | Configure Event Weights (Admin) | ⚠️ Diverged | `PUT /weights/{key}` exists and works, but has no admin auth check — any user can update weights. No logging of weight changes. Story says only future scoring affected; `recalculate` endpoint explicitly re-scores all historical data, which contradicts this. |
| 6.3 | Card Modifier Scoring | 🔲 Not implemented | No card modifier system; scoring is purely stat-weight based with no per-card bonus. |
| 6.4 | Track Season Points | ✅ Aligned | Season points computed from all locked weekly roster entries; displayed on My Team tab and season leaderboard. |
| 6.5 | Track Points per Card | ⚠️ Diverged | Weekly points per card are shown in the roster view. However, there is no dedicated per-card historical tracking across weeks — only the current selected week's contribution is visible. |
| 6.6 | Prevent Duplicate Scoring | ❓ Ambiguous | Relies on `match_id` as primary key in `matches` and composite uniqueness in `player_match_stats`. Cannot fully verify without seeing `ingest.py` for upsert logic. |
| 7.1 | Fetch Player Data | ❓ Ambiguous | `ingest_league` and `run_enrichment` are called but implementations are in separate files not provided. Endpoint exists. |
| 7.2 | Import Match Data | ❓ Ambiguous | Same as 7.1 — `ingest_league` presumably imports match data but implementation not visible. |
| 7.3 | Handle API Failures | ⚠️ Diverged | Auto-ingest wraps each league in try/except and prints error; no retry logic, no admin-visible failure log or alert. |
| 8.1 | Season Leaderboard | ✅ Aligned | `/leaderboard/season` ranks users by total season points from locked weekly rosters. |
| 8.2 | Scrollable Leaderboard | ✅ Aligned | Leaderboard is in a separate tab; standard HTML table is scrollable in the browser. |
| 8.3 | Show User Rank | ⚠️ Diverged | Logged-in user's row is highlighted (gold color, bold) in the leaderboard, but their rank is not persistently visible outside the leaderboard tab (e.g., not in the header). |
| 8.4 | Weekly Leaderboard | ✅ Aligned | `/leaderboard/weekly?week_id=` endpoint exists; UI has Season/Weekly toggle with week selector. |
| 9.1 | Generate Codes | ✅ Aligned | Duplicate of 5.5; covered. |
| 9.2 | Grant Tokens | ✅ Aligned | `/grant-tokens` admin endpoint grants tokens to target user; UI in admin tab. |
| 9.3 | Configure Scoring | ⚠️ Diverged | Duplicate of 6.2; weights endpoint lacks admin auth and change logging. |
| 9.4 | Manage Season Lifecycle | 🔲 Not implemented | No explicit season start/end/archive controls. Weeks are auto-generated but no season entity or lifecycle management exists. |
| 9.5 | View System Status | 🔲 Not implemented | No system status dashboard; `/schedule/debug` partially exposes schedule URL health but is not a general status view. |
| 9.6 | Start New Season | 🔲 Not implemented | No new-season endpoint; no mechanism to archive current season data and reset. |
| 10.1 | Explain Scoring | ✅ Aligned | "How is scoring calculated?" toggle in My Team tab explains stat-to-point mapping with formula and weight names. |
| 11.1 | Server-side Validation | ⚠️ Diverged | Registration and code redemption have server validation. However, auth is client-side only (no session tokens) — any API caller can impersonate any user by passing their `user_id`. Roster activate/deactivate don't check week lock server-side. |
| 11.2 | Audit Logs | 🔲 Not implemented | No audit log table or mechanism. `CodeRedemption` has timestamps but draws, re-rolls, admin actions, registration rewards, and season resets are not logged. |
| 12.1 | Player Browser | ✅ Aligned | Players tab with search, match count, avg/total points; player detail modal with full match history. |
| 12.2 | Team Browser | ✅ Aligned | Teams tab listing teams with match/player count; team detail modal with roster. |
| 12.3 | Schedule Tab | ✅ Aligned | Schedule tab shows season schedule; team names are clickable and open team modal. |
| 12.4 | User Profile Tab | ✅ Aligned | Profile tab allows editing display name and linking OpenDota player ID. |
| 12.5 | Week History Selector | ✅ Aligned | Dropdown on My Team tab allows viewing any past locked week's snapshot roster and points. |
| 12.6 | Auto-ingest on Startup | ✅ Aligned | `AUTO_INGEST_LEAGUES` env var controls startup ingestion; skips existing data via `ingest_league`. |
| 12.7 | Admin: Recalculate Points | ✅ Aligned | `/recalculate` endpoint re-scores all `player_match_stats` with current weights. |
| 12.8 | Admin: Manual League Ingestion | ✅ Aligned | `/ingest/league/{league_id}` with admin check; UI in admin tab. |
| 12.9 | Admin: Schedule Refresh | ✅ Aligned | `/schedule/refresh` busts cache and re-fetches from Google Sheets. |
| 12.10 | Admin: Grant Draws to User | ⚠️ Diverged | Admin can grant tokens (which are used for draws), but there's no separate "grant draws" concept — tokens and draws are the same resource. The story implies a draw-specific grant distinct from tokens. Clarify whether this is the same as token granting. |

## Key divergences

1. **No server-side authentication/session management (1.2, 11.1):** All "auth" is client-side `localStorage`; any API consumer can impersonate any user by supplying their `user_id`. — *Update implementation* to add session tokens or JWT.

2. **Card modifiers not implemented (3.5, 3.6, 5.7, 6.3):** The Card model has no modifier fields; no modifier generation, display, re-roll, or scoring bonus exists. This affects four stories. — *Update implementation* to add modifier system, or *clarify stories* to defer to post-MVP.

3. **Roster lock not enforced server-side (4.1, 4.2):** `activate`/`deactivate` endpoints do not check whether the current week is locked; no scheduled auto-lock job runs (only at startup). — *Update implementation* to check lock status on roster mutations and add a periodic lock task.

4. **No automatic roster carry-over between weeks (2.4):** Story requires the previous week's active roster to carry forward; implementation does not snapshot or propagate rosters to the next week. — *Update implementation* to copy roster entries when a new week begins.

5. **Free weekly token not granted (5.1):** No mechanism exists to give all users 1 token when a week locks. — *Update implementation* to add token grant on week-lock event.

6. **Weight update endpoint lacks admin auth (6.2, 9.3):** `PUT /weights/{key}` has no `require_admin` call; any user can change scoring weights. No change logging either. — *Update implementation* to add admin check and audit logging.

7. **No forgot-password / temporary password flow (1.3):** No email sending or temporary credential mechanism exists. — *Update implementation* or *clarify story* to defer if email infra is out of scope for POC.

8. **No audit log system (11.2, 5.2):** Only `CodeRedemption` records redemptions with timestamps; draws, token grants, admin actions, re-rolls, and registration events are not logged. — *Update implementation* to add an audit log table.

9. **Season lifecycle management missing (9.4, 9.6):** No ability to start, end, or archive a season. No season entity beyond auto-generated weeks. — *Update implementation* or *clarify stories* for MVP scope.

10. **Draw deduplication logic diverges from story (5.3):** Story allows only higher-rarity duplicates when user owns all players; implementation allows any duplicate as fallback with
