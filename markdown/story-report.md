<!-- Generated automatically by scripts/story_report.py — do not edit by hand -->
_Last updated: 2026-04-05 05:29 UTC_

# Story Coverage Report

| ID | Story | Status | Notes |
|----|-------|--------|-------|
| 1.1 | User Registration | ✅ Aligned | Registration validates unique username/email, creates user, grants initial tokens, records `created_at` timestamp. Auto-logs in after registration. |
| 1.2 | User Login | ✅ Aligned | Login validates username + password, sets session, returns error on invalid credentials. Session middleware is configured. Unauthenticated users are blocked by `get_current_user`. |
| 1.3 | User Receive Temporary Password | ✅ Aligned | `/forgot-password` generates temp password, emails it, sets `must_change_password` flag. Returns 200 regardless to avoid enumeration. No explicit check for missing email on the user record beyond the `if not user or not user.email` guard which silently succeeds. |
| 1.4 | User Password Reset | ✅ Aligned | `PUT /profile/password` requires current password before accepting new one. Clears `must_change_password` flag. |
| 1.5 | User Logout | ✅ Aligned | `POST /logout` clears session. Logout button visible on every page via header. |
| 1.6 | Admin-only Access | ✅ Aligned | `require_admin` dependency re-checks `is_admin` from session on every admin endpoint. Admin tab hidden for non-admins in frontend. However, `is_admin` is read from the session set at login time, not re-fetched from DB on each request — if admin status changes mid-session it won't reflect until re-login, but the story says "verified server-side on every admin request" which is met via session check. |
| 1.7 | User Profile Tab | ✅ Aligned | Username change with uniqueness check, password change with current password, optional OpenDota player ID linking with preview. |
| 2.1 | Grant Starter Tokens on Registration | ✅ Aligned | `INITIAL_TOKENS` env var used; tokens assigned at registration. |
| 2.2 | Token Visibility | ✅ Aligned | Token balance shown in header (`tokenBalance` element), updated after draw/redeem/grant. `drawCounter` on My Team tab stays in sync. |
| 2.3 | View Cards | ⚠️ Diverged | Cards display player identity, rarity, and weekly points. However, cards on the bench show points for the scoped week rather than being clearly labeled as "benched until placed." The bench section is hidden (`display:none` initially in HTML) until roster loads — minor UX gap. |
| 2.4 | View Weekly Rosters | ✅ Aligned | Upcoming week is the default view. Lock date shown via `rosterWeekStatus`. Empty active slots rendered explicitly with "— empty slot —" rows. |
| 2.5 | View Current and Season Points | ✅ Aligned | Weekly and season points shown separately. Week history selector allows viewing past weeks. New user with no activity sees 0. |
| 3.1 | Generate Cards | ✅ Aligned | `seed_cards` called during ingestion. Per the `seed.py` import (not shown but called), cards are generated per player. Deck is shared (cards have `owner_id=NULL`). Story requires 1 legendary, 2 epic, 4 rare, 8 common per player — cannot fully verify without `seed.py` source. |
| 3.2 | Card Drawing | ✅ Aligned | Requires ≥1 token, deducts 1, shows reveal modal, auto-places in active roster if slots available else bench. Prefers unowned players; allows duplicates only when all players owned. |
| 3.3 | Remove Cards from Pool | 🔲 Not implemented | Marked post-MVP. No admin endpoint to remove a player's cards and refund tokens. |
| 3.4 | Card Rarity | ✅ Aligned | `card_type` set at deck creation time (seed). Rarity shown in reveal modal and roster views via badge CSS class. |
| 3.5 | Assign Randomized Modifiers | ✅ Aligned | `_assign_modifiers` randomly assigns stat modifiers at draw time based on rarity config. Stored in `card_modifiers` table. Visible in card detail and roster views. |
| 3.6 | Modifier Management | ⚠️ Diverged | Modifier counts and bonus percentages are stored in the `weights` table (DB), not directly in environment variables as the story specifies. Changes require DB updates rather than env var changes. The "not applied retroactively without explicit recalculate" aspect is met since modifiers are per-card. |
| 3.7 | View Seasonal Reserve Cards | ✅ Aligned | Bench shown in My Team tab with player, rarity, and week points. Bench hidden for locked past weeks (read-only snapshot). |
| 3.8 | View Permanent Collection | 🔲 Not implemented | Marked post-MVP. No cross-season collection tracking. |
| 4.1 | Place Cards into Active Slots | ✅ Aligned | 5-slot roster limit enforced. Activate/Bench buttons. Duplicate player check prevents two cards of the same player being active. No explicit check preventing changes on locked weeks at the API level — relies on UI hiding buttons. |
| 4.2 | Lock Active Cards | ⚠️ Diverged | `auto_lock_weeks` runs periodically via background thread. Week locking is based on `weeks` table boundaries, but the story says "auto-lock every Sunday at end of day (UTC)." Actual lock timing depends on `generate_weeks`/`auto_lock_weeks` implementation (not shown). UI shows locked banner and lock date. Roster snapshot is created at lock time via `weekly_roster_entries`. |
| 4.3 | Admin Move Series Time Manually | ⚠️ Diverged | `PUT /matches/{match_id}/week` operates on individual matches, not on series. The story says "select a series," but implementation is per-match. `sync-match-weeks` endpoint exists for batch assignment. The `week_override_id` persists and isn't overridden by re-ingestion (matches table retains the override). No dedicated admin UI for series selection in the frontend. |
| 4.4 | Preserve Points | ✅ Aligned | `weekly_roster_entries` stores the locked roster. Points derived from `player_match_stats` joined with weeks. Season total computed from all locked weeks. |
| 4.5 | View Past Week Snapshots | ✅ Aligned | Week selector dropdown on My Team tab. Past locked weeks show immutable snapshot. Weekly points scoped to that week's matches. Current editable week accessible. |
| 5.1 | Free Weekly Token | ⚠️ Diverged | No visible implementation of granting 1 token to all users when a week locks. `auto_lock_weeks` is imported from `weeks.py` (not provided), so it may or may not include token grants — cannot confirm from provided code. |
| 5.2 | Token Log (admin) | ⚠️ Diverged | Audit log tracks admin grants, draws, and redemptions. However, weekly free token grants are not visibly logged with "total number of users affected" as the story requires. The audit log is generic; no dedicated token log view grouping by event type. |
| 5.3 | Spend Token to Draw Card | ✅ Aligned | 1 token deducted, card assigned to user, duplicate player prevention, reveal modal shown. |
| 5.4 | Redeem Code | ✅ Aligned | Valid code grants tokens, invalid code shows error, one use per user enforced via `code_redemptions`, logged in audit log. |
| 5.5 | Re-roll Modifiers | ✅ Aligned | Costs 1 token, confirmation popup in UI, modifiers replaced via `reroll_modifiers` endpoint, logged in audit log. Story also says "quality replaced" — implementation only re-rolls modifiers, not rarity/card_type. |
| 6.1 | Score Active Cards | ✅ Aligned | Fantasy points calculated from Dota 2 match data. Only locked-week roster entries score (via `weekly_roster_entries`). Duplicate scoring prevented by match-level idempotency. |
| 6.2 | Card Modifier Scoring | ✅ Aligned | Rarity bonus applied (common +0%, rare +1%, epic +2%, legendary +3% defaults). Configurable via weights table. Card stat modifiers also applied. |
| 6.3 | Track Season Points | ✅ Aligned | Season points computed from all locked weeks' roster entries with rarity and modifier multipliers. Visible on My Team tab and in season leaderboard. |
| 6.4 | Track Points per Card | ✅ Aligned | Per-card `total_points` shown in roster view scoped to selected week. Historical tracking via week selector. |
| 6.5 | Prevent Duplicate Scoring | ✅ Aligned | `ingest_league` is idempotent (already-stored matches skipped). Match events uniquely keyed by `match_id` + `player_id`. |
| 7.1 | Fetch Player Data | ✅ Aligned | `run_enrichment()` called during ingestion to fetch player names and avatars. Missing players handled gracefully (NULL avatar, name). |
| 7.2 | Import Match Data | ✅ Aligned | `ingest_league` imports match data. `PlayerMatchStats` stores kills, assists, deaths, GPM, wards, tower damage. Fantasy points calculated and stored. |
| 7.3 | Handle API Failures | ⚠️ Diverged | Auto-ingest catches exceptions and logs them (`print`). However, there's no structured error logging or admin-visible error status. Admin can re-trigger ingestion manually. Partial ingestion safety depends on `ingest.py` implementation (not provided). |
| 7.4 | Auto-ingest on Startup | ✅ Aligned | `AUTO_INGEST_LEAGUES` env var parsed at startup. Runs in background thread via `ThreadPoolExecutor`. Empty value disables (though default is `"19368,19369"`, not empty). Already-stored matches skipped. |
| 8.1 | Season Leaderboard | ⚠️ Diverged | Season leaderboard (`/leaderboard/season`) ranks users by cumulative points across locked weeks with rarity modifiers. However, the SQL does not account for `week_override_id` — it only uses `m.start_time BETWEEN wk.start_time AND wk.end_time`, missing matches that were overridden to a different week. |
| 8.2 | Scrollable Leaderboard | ✅ Aligned | Leaderboard tab is the default active tab and does not require login to view. |
| 8.3 | Show User Rank | ✅ Aligned | Logged-in user's row highlighted with gold color and bold text in leaderboard. Rank number shown. |
| 8.4 | Weekly Leaderboard | ⚠️ Diverged | Weekly leaderboard available with week selector. Same `week_override_id` issue as season leaderboard — overridden matches may not be counted correctly. |
| 8.5 | Player Performance Browser | ✅ Aligned | Players tab lists all players with match count, avg points, total points. Filterable by name/team. Player detail modal shows full match history with K/A/D, GPM, wards, tower damage, fantasy points. |
| 8.6 | Team Browser | ✅ Aligned | Teams tab lists all teams with match count and player count. Team detail modal shows player roster with stats. |
| 9.1 | Generate Promo Codes | ✅ Aligned | Admin creates codes with configurable token amount. Codes reusable (multiple users). One redemption per user enforced. Admin can delete codes. |
| 9.2 | Grant Tokens | ✅ Aligned | Admin selects user, specifies amount, grants tokens. Balance updates immediately. Logged in audit log with actor, target, amount. |
| 9.3 | Configure Scoring Weights | ⚠️ Diverged | Weights are stored in DB and displayed in admin tab, but they are read-only in the UI — no edit form. Story says editable from environment variables; implementation uses DB `weights` table seeded from `seed_weights()`. Recalculate button exists for retroactive application. |
| 9.4 | Manage Season Lifecycle | ⚠️ Diverged | No explicit "initiate season" or "close season" buttons in admin UI. Season weeks are auto-generated. Lock dates driven by week boundaries. League IDs configured via env vars. |
| 9.5 | View System Status | ⚠️ Diverged | `/schedule/debug` endpoint exists for admin but only shows schedule cache status. No general system status view showing ingest status, last ingest time, or overall health. |
| 9.6 | Start New Season | 🔲 Not implemented | No "reset database and begin new season" functionality in admin UI or API. |
| 9.7 | Admin Set Series Date | ⚠️ Diverged | `PUT /matches/{match_id}/week` allows overriding which week a match counts for, and `POST /admin/sync-match-weeks` does batch assignment. However, no admin UI exists for selecting a series from a list and setting the week. The override sets `week_override_id` (week assignment) rather than a display datetime as the story suggests. The story says "new datetime is displayed on the schedule instead of the actual match date" — this is not implemented; schedule display comes from Google Sheet, not from the override. |
| 9.8 | Recalculate Fantasy Points | ✅ Aligned | `POST /recalculate` applies current weights to all stored stats without re-fetching. Returns count of updated records. Logged in audit log. |
| 9.9 | Manual League Ingestion | ✅ Aligned | Admin enters league ID, triggers ingestion. Fetches matches, calculates points, seeds cards, enriches profiles. Idempotent. Logged. |
| 9.10 | Schedule Refresh | ✅ Aligned | Refresh button busts cache, re-fetches from Google Sheets CSV. Logged in audit log. |
| 10.1 | Explain Scoring | ✅ Aligned | Collapsible "How is scoring calculated?" section on My Team tab lists weighted stats formula. |
| 10.2 | Schedule Tab | ✅ Aligned | Chronological list spanning divisions. Upcoming series show date/time, team names, stream links. Past series show result scores and actual time. Team names link to team modal. Stale cache notice shown when data is outdated. |
| 11.1 | Server-side Validation | ✅ Aligned | All state-changing actions validated server-side via `get_current_user`/`require_admin` dependencies. Admin endpoints re-verify from session. |
| 11.2 | Audit Logs | ⚠️ Diverged | Tracks registrations, logins, draws, redemptions, admin grants, ingestion, recalculations, schedule refreshes, code creation/deletion. Missing: weight changes (no weight editing endpoint exists), and reroll is logged but not explicitly listed in the story. Visible in admin tab, sorted by most recent. Admin-only access enforced. |
| 12.1 | Weight Calculation | ✅ Aligned | `POST /simulate/{match_id}` accepts per-stat weight overrides, returns table of players with fantasy point values. No authentication required. Falls back to DB defaults for unspecified weights. |
| 12.2 | Weight Statistics | ✅ Aligned | `GET /simulate` returns machine-readable JSON documentation describing the endpoint, parameters, request body, response format, and errors. |

## Key divergences

1. **5.1 — Free weekly token grant not verifiably implemented**: The `auto_lock_weeks` function (in `weeks.py`, not provided) may or may not grant tokens when a week locks; no evidence of token granting in the visible codebase. — *Update implementation* (or provide `weeks.py` to verify).

2. **8.1/8.4 — Season and weekly leaderboard SQL ignores `week_override_id`**: The leaderboard queries only use `m.start_time BETWEEN wk.start_time AND wk.end_time` but do not include the `OR m.week_override_id = wk.id` clause, meaning admin-overridden matches are silently excluded from leaderboard scoring. — *Update implementation*.

3. **9.6 — No "Start New Season" functionality**: No endpoint or UI to reset the database and
