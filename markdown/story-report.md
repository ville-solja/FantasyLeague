<!-- Generated automatically by scripts/story_report.py — do not edit by hand -->
_Last updated: 2026-03-31 17:01 UTC_

# Story Coverage Report

| ID | Story | Status | Notes |
|----|-------|--------|-------|
| 1.1 | User Registration | ✅ Aligned | Registration checks unique username/email, grants initial tokens, records `created_at` timestamp, and creates the account. |
| 1.2 | User Login | ⚠️ Diverged | Login works with username+password and returns session. However, logged-out users can still access several GET endpoints (e.g. `/roster/{user_id}`, `/players`, `/teams`) without authentication; only write endpoints are protected. |
| 1.3 | User Receive Temporary Password | 🔲 Not implemented | No forgot-password or temporary-password endpoint exists; no email sending capability. |
| 1.4 | User Password Reset | ✅ Aligned | `PUT /profile/password` requires current password before accepting a new one. UI exists in Profile tab. |
| 1.5 | User Logout | ⚠️ Diverged | Logout clears session and redirects client-side via `applyAuthState()`, but JS redirects to the leaderboard tab only if logged out on init; `logout()` calls `applyAuthState()` which does `switchTab("leaderboard")` — aligned. Session invalidation is present. |
| 1.6 | Admin-only Access | ✅ Aligned | `require_admin` dependency re-verifies `is_admin` from session on every admin endpoint; admin tab hidden for non-admins. Server-side check queries session, not just client flag. Note: session stores `is_admin` from login time — if admin status changes, the session is stale until re-login. |
| 1.7 | User Profile Tab | ✅ Aligned | Username change (unique enforced), password change (current required), OpenDota player ID linking with preview all implemented. |
| 2.1 | Grant Starter Tokens on Registration | ✅ Aligned | `INITIAL_TOKENS` env var configures count; granted at registration. |
| 2.2 | Token Visibility | ✅ Aligned | Token balance shown in header via `#tokenBalance`, updates after draw/redeem/grant. `drawCounter` in My Team tab stays in sync. |
| 2.3 | View Cards | ✅ Aligned | Drawn cards display player name, avatar, rarity, and weekly points. Cards visible in My Team tab as active or bench. |
| 2.4 | View Weekly Rosters | ⚠️ Diverged | Upcoming week's roster is shown via week selector, but the lock timing shown is derived from `week.start_time - 1` rather than an explicit "Sunday end of day" display. Empty slots are shown explicitly. |
| 2.5 | View Current and Season Points | ✅ Aligned | Weekly and season point pools shown separately in My Team tab. Week history selector allows viewing past weeks. New user with no activity will show 0. |
| 3.1 | Generate Cards | ✅ Aligned | `seed_cards` generates 1 legendary, 2 epic, 4 rare, 8 common per player from league match data. Idempotent via checking existing cards. Shared deck (cards with `owner_id IS NULL`). |
| 3.2 | Card Drawing | ✅ Aligned | Requires ≥1 token, shows reveal modal, auto-places to active if slots available else bench. Prefers players user doesn't own; allows duplicates only when all players owned. |
| 3.3 | Remove Cards from Pool | 🔲 Not implemented | Marked post-MVP; no admin endpoint to remove player cards or refund tokens. |
| 3.4 | Assign Randomized Card Rarity | ⚠️ Diverged | Rarity is fixed at deck creation time (per `seed_cards`) — this is correct. However, the story says "randomized" but implementation uses a fixed distribution (1/2/4/8). Rarity is shown in reveal modal and roster. The word "randomized" in the story may be misleading. |
| 3.5 | Assign Randomized Modifiers | 🔲 Not implemented | The `Card` model has no `modifiers` column. No modifier assignment logic exists. Cards only have `card_type` (rarity). |
| 3.6 | Modifier Management | 🔲 Not implemented | No per-card modifiers exist to manage. Rarity modifier weights are configurable, but individual card modifiers are absent. |
| 3.7 | View Seasonal Reserve Cards | ✅ Aligned | Bench cards shown in My Team tab. Cards display player, rarity, and weekly points. Bench hidden for locked past weeks (snapshot view). |
| 3.8 | View Permanent Collection | 🔲 Not implemented | Marked post-MVP. No cross-season collection tracking. |
| 4.1 | Place Cards into Active Slots | ✅ Aligned | 5 slots enforced via `ROSTER_LIMIT`. Activate/Bench (deactivate) endpoints exist. Duplicate player check prevents two cards of same player active. |
| 4.2 | Lock Active Cards | ⚠️ Diverged | `auto_lock_weeks` locks weeks on startup, but there's no periodic scheduler — weeks only lock when server restarts or code is triggered manually. No cron/background task runs to lock at Sunday EOD UTC in real time. UI shows locked banner and lock date. |
| 4.3 | Admin Move Series Time Manually | 🔲 Not implemented | No endpoint to view/select series or override match dates. Schedule data comes from Google Sheets; no series date override mechanism exists. |
| 4.4 | Preserve Points | ✅ Aligned | `weekly_roster_entries` snapshots store locked week rosters. Points derived from `player_match_stats` scoped by week time range. Season total derivable from past week records. |
| 4.5 | View Past Week Snapshots | ✅ Aligned | Week selector dropdown lists all weeks. Past locked weeks show immutable snapshot. Weekly points scoped to that week's time range. Current editable week accessible. |
| 5.1 | Free Weekly Token | ⚠️ Diverged | No implementation found for granting 1 free token to all users when a week locks. `auto_lock_weeks` locks weeks but does not grant tokens. |
| 5.2 | Token Log (admin) | ⚠️ Diverged | Audit log tracks draws, redemptions, admin grants — but there's no summary view of weekly free token grants with user counts (because weekly grants aren't implemented). Token events are logged individually. |
| 5.3 | Spend Token to Draw Card | ✅ Aligned | 1 token deducted, card assigned to user, duplicate-player prevention, reveal modal shown. |
| 5.4 | Redeem Code | ✅ Aligned | Valid code grants tokens, invalid shows error, one use per user enforced, logged in audit. |
| 5.5 | Re-roll Modifiers | 🔲 Not implemented | No re-roll endpoint. No modifiers on cards to re-roll. No confirmation popup. |
| 6.1 | Score Active Cards | ✅ Aligned | Only locked roster entries score. Points derived from Dota match data. Duplicate scoring prevented by unique match_id tracking. |
| 6.2 | Card Modifier Scoring | ⚠️ Diverged | Rarity bonus percentages applied (common +0%, rare +1%, epic +2%, legendary +3% defaults). Configurable via admin weights. However, story mentions "modifiers" beyond rarity which don't exist. |
| 6.3 | Track Season Points | ✅ Aligned | Season points calculated across all locked weeks with rarity modifiers. Visible on My Team tab and season leaderboard. |
| 6.4 | Track Points per Card | ✅ Aligned | Per-card weekly points shown in roster view. Historical tracking via week selector. |
| 6.5 | Prevent Duplicate Scoring | ✅ Aligned | Match data keyed by `match_id` (primary key). Idempotent ingestion skips existing records. |
| 7.1 | Fetch Player Data | ✅ Aligned | `run_enrichment` fetches player names and avatars from OpenDota. Missing players handled gracefully (name/avatar remain null). |
| 7.2 | Import Match Data | ✅ Aligned | `ingest_league` fetches match data with K/A/D, GPM, wards, tower damage. Fantasy points calculated and stored per player-match. |
| 7.3 | Handle API Failures | ⚠️ Diverged | Auto-ingest catches exceptions and prints them but there's no explicit partial-ingestion rollback guarantee in `ingest_league`. Admin can re-trigger. Logging is print-based, not to audit log for API failures. |
| 7.4 | Auto-ingest on Startup | ⚠️ Diverged | Runs in background thread on startup. Default is `"19368,19369"` not empty — story says setting empty disables it, but default is non-empty, so auto-ingest runs by default even without explicit config. Already-stored matches skipped. |
| 8.1 | Season Leaderboard | ✅ Aligned | Users ranked by cumulative fantasy points across locked weeks. Only active roster snapshot cards counted. Rarity modifiers applied. |
| 8.2 | Scrollable Leaderboard | ✅ Aligned | Leaderboard tab visible without login (`applyAuthState` shows leaderboard for logged-out users). Rendered as a table (scrollable by default). |
| 8.3 | Show User Rank | ✅ Aligned | Logged-in user's row highlighted with gold color and bold text in the leaderboard. |
| 8.4 | Weekly Leaderboard | ✅ Aligned | Weekly mode with week selector alongside season view. Can view any locked week. |
| 8.5 | Player Performance Browser | ✅ Aligned | Players tab lists all players with match count, avg/total points. Filterable by name/team. Player detail modal shows full match history with per-match stats. |
| 8.6 | Team Browser | ✅ Aligned | Teams tab lists teams with match count and player count. Team detail modal shows player roster with stats. |
| 9.1 | Generate Promo Codes | ✅ Aligned | Admin creates codes with token amount. Codes are reusable (multiple users). One redemption per user. Admin can delete codes. |
| 9.2 | Grant Tokens | ✅ Aligned | Admin selects user and grants tokens. Balance updates immediately. Logged in audit with actor, target, amount. |
| 9.3 | Configure Scoring Weights | ✅ Aligned | All stat weights editable from admin tab. Rarity modifier percentages also configurable. Recalculate button exists separately. |
| 9.4 | Manage Season Lifecycle | ⚠️ Diverged | No explicit "initiate" or "close" season UI/endpoint. Season configuration is env-var driven. Week generation happens automatically on startup. No admin button to start/end season. |
| 9.5 | View System Status | ⚠️ Diverged | `/schedule/debug` endpoint exists (admin only) showing schedule URL and fetch status, but no comprehensive system status dashboard showing ingest status or general health. |
| 9.6 | Start New Season | 🔲 Not implemented | No database reset or new season initialization endpoint. Migration code exists for week structure but no admin-triggered season reset. |
| 9.7 | Admin Set Series Date | 🔲 Not implemented | No series list view or date override endpoint. Schedule data from Google Sheets has no override mechanism. |
| 9.8 | Recalculate Fantasy Points | ✅ Aligned | Recalculate applies current weights to all stored stats without re-fetching. Returns count of updated records. Logged in audit. |
| 9.9 | Manual League Ingestion | ✅ Aligned | Admin enters league ID, triggers ingestion. Fetches matches, calculates points, seeds cards, enriches profiles. Idempotent. Logged. |
| 9.10 | Schedule Refresh | ✅ Aligned | Refresh button busts cache, fetches from Google Sheets CSV URL. Logged in audit. |
| 10.1 | Explain Scoring | ✅ Aligned | Collapsible "How is scoring calculated?" section in My Team tab lists weighted stats formula. |
| 10.2 | Schedule Tab | ⚠️ Diverged | All series shown chronologically across divisions. Upcoming/past series displayed with dates, teams, stream links. Team names are clickable. However: VOD links not explicitly handled (only `stream_url` used for both); stale cache notice implemented. Series results shown when available. |
| 11.1 | Server-side Validation | ✅ Aligned | All state-changing actions use `Depends(get_current_user)` or `Depends(require_admin)`. Admin endpoints re-verify from session, not client state. |
| 11.2 | Audit Logs | ⚠️ Diverged | Tracks: registrations, logins, draws, redemptions, admin grants, ingestion, weight changes, recalculations, schedule refreshes, code creation/deletion. Each entry has timestamp, actor, action, detail. Admin-only, most recent first. However, roster changes (activate/deactivate) are not logged. |

## Key divergences

1. **1.3 — Temporary password / forgot password flow is completely missing.** No email-sending infrastructure exists. — *Update implementation.*

2. **3.5/3.6/5.5 — Card modifiers system is entirely absent.** Cards have rarity but no individual modifiers, no modifier storage, no re-roll feature. This is a fundamental feature gap across multiple stories. — *Clarify story (are modifiers deferred to post-MVP?) or update implementation.*

3. **5.1 — Free weekly token grant is not implemented.** `auto_lock_weeks` locks weeks but never grants the +1 token to all users. — *Update implementation.*

4. **4.2 — Week locking has no real-time scheduler.** Weeks only lock on server startup via `auto_lock_weeks`; there is no background cron or periodic task to lock at Sunday EOD UTC while the server is running. — *Update implementation.*

5. **9.7/4.3 — Admin series date override is not implemented.** No endpoint to list series, select one, or persist a corrected date that survives re-ingestion. — *Update implementation.*

6. **9.6 — Start new season / database reset is not implemented.** No admin-facing way to close the current season and begin a new one with fresh state. — *Update implementation.*

7. **9.4 — Season lifecycle management has no explicit UI.** No admin buttons to initiate or close a season; everything relies on environment variables and server restarts. — *Update implementation.*

8. **7.4 — Auto-ingest default is non-empty (`"19368,19369"`).** The story says empty disables it, but the implementation defaults to active leagues, meaning auto-ingest runs even without explicit configuration. — *Update implementation to default to empty string.*

9. **9.5 — System status view is minimal.** Only a schedule debug endpoint exists; no dashboard showing ingest status, last ingest time, database stats, or overall health. — *Update implementation.*

10. **11.2 — Audit log is missing coverage for roster changes (activate/deactivate cards).** These state-changing actions are not logged despite other user actions being tracked. — *Update implementation.*
