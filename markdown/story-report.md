<!-- Generated automatically by scripts/story_report.py — do not edit by hand -->
_Last updated: 2026-04-07 14:09 UTC_

# Story Coverage Report

| ID | Story | Status | Notes |
|----|-------|--------|-------|
| 1.1 | User Registration | ✅ Aligned | `/register` validates unique username/email, grants initial tokens, records `created_at` timestamp. |
| 1.2 | User Login | ✅ Aligned | `/login` validates username+password, returns error on invalid credentials, session-based auth gates protected routes. |
| 1.3 | User Receive Temporary Password | ✅ Aligned | `/forgot-password` generates temp password, emails it, sets `must_change_password` flag. Returns 200 regardless to avoid enumeration. |
| 1.4 | User Password Reset | ✅ Aligned | `PUT /profile/password` requires current password before accepting new one. Profile page has the form. |
| 1.5 | User Logout | ✅ Aligned | `/logout` clears session; logout button visible on every page in the header. |
| 1.6 | Admin-only Access | ✅ Aligned | `require_admin` dependency re-verifies `is_admin` from DB session on every admin endpoint; admin tab hidden for non-admins in frontend. |
| 1.7 | User Profile Tab | ✅ Aligned | Username change with uniqueness check, password change form, optional OpenDota player ID with name/avatar preview all implemented. |
| 2.1 | Grant Starter Tokens on Registration | ✅ Aligned | `INITIAL_TOKENS` env var used; tokens set at registration. |
| 2.2 | Token Visibility | ✅ Aligned | Token balance shown in header (`tokenBalance`) and synced with `drawCounter` on My Team tab; updated after draw, redeem, and grant events. |
| 2.3 | View Cards | ✅ Aligned | Drawn cards show player identity, rarity, and week points; bench/active distinction visible on My Team tab. |
| 2.4 | View Weekly Rosters | ⚠️ Diverged | Upcoming week is the default view and empty slots are shown. However, the lock date display shows lock timing but the story says "clearly visible when the roster will be locked" — implementation shows a formatted date which is adequate. Minor: no explicit countdown or prominent lock indicator beyond text. |
| 2.5 | View Current and Season Points | ✅ Aligned | Weekly and season points shown separately on My Team tab; week selector enables viewing past weeks; 0 for new users. |
| 3.1 | Generate Cards | ✅ Aligned | `seed_cards` generates cards per player (1 legendary, 2 epic, 4 rare, 8 common) from ingested league data; idempotent seeding via `seed_cards`. |
| 3.2 | Card Drawing | ✅ Aligned | Token required, reveal modal shown, auto-placed to active if slots available else bench, prefers unowned players with fallback to duplicates. |
| 3.3 | Remove Cards from Pool | 🔲 Not implemented | Marked post-MVP; no admin endpoint to remove a player's cards and refund tokens. |
| 3.4 | Card Rarity | ✅ Aligned | Rarity set at deck creation time (seed), not at draw time; displayed in reveal modal and roster views. |
| 3.5 | Assign Randomized Modifiers | ✅ Aligned | `_assign_modifiers` creates `CardModifier` rows at draw time; modifiers stored in DB and visible on card views. |
| 3.6 | Modifier Management | ⚠️ Diverged | Story says modifiers managed from environment variables. Implementation uses `Weight` DB rows (e.g. `modifier_count_common`, `modifier_bonus_pct`) seeded via `seed_weights`. These are DB-managed, not env vars. Recalculate action exists but doesn't explicitly re-apply modifier weights to existing cards. |
| 3.7 | View Seasonal Reserve Cards | ✅ Aligned | Bench section visible on My Team tab for current week; hidden for locked past weeks (snapshot view). Shows player, rarity, points. |
| 3.8 | View Permanent Collection | 🔲 Not implemented | Marked post-MVP; no cross-season collection view. |
| 4.1 | Place Cards into Active Slots | ✅ Aligned | 5 slots, activate/deactivate endpoints, duplicate player check, only editable on current week (locked weeks show read-only). |
| 4.2 | Lock Active Cards | ⚠️ Diverged | `auto_lock_weeks` runs periodically and locks weeks. Week boundaries defined by `generate_weeks`. Story says "auto-lock every Sunday at end of day (UTC)" — implementation uses week `start_time` for lock timing (locks before matches start), which may differ from Sunday EOD. Locked banner and immutable snapshot are implemented. |
| 4.3 | Admin Move Series Time Manually | ⚠️ Diverged | `PUT /matches/{match_id}/week` overrides which week a match counts for, and `sync-match-weeks` automates this. Story says "series" but implementation works at match level, not series level. No UI in admin tab to browse/select series — only API endpoints exist. |
| 4.4 | Preserve Points | ✅ Aligned | `WeeklyRosterEntry` snapshots created on lock; season points derived from past week records. |
| 4.5 | View Past Week Snapshots | ✅ Aligned | Week selector dropdown lists all weeks; past locked weeks show immutable roster with week-scoped points. |
| 5.1 | Free Weekly Token | ⚠️ Diverged | No code found in the provided codebase that grants 1 token to all users when a week is locked. `auto_lock_weeks` in `weeks.py` is not shown, but `main.py` doesn't contain this logic either. Likely missing or in unseen `weeks.py`. |
| 5.2 | Token Log (admin) | ⚠️ Diverged | Audit log tracks `admin_grant_tokens`, `token_draw`, `token_redeem`. However, weekly free token grants are not logged with "total number of users affected" as specified. No dedicated token log view — events are mixed in generic audit log. |
| 5.3 | Spend Token to Draw Card | ✅ Aligned | 1 token deducted, card assigned to user, duplicate avoidance logic, reveal modal shown. |
| 5.4 | Redeem Code | ✅ Aligned | Valid code grants tokens, invalid code shows error, one use per user, logged in audit log. |
| 5.5 | Re-roll Modifiers | ⚠️ Diverged | Costs 1 token, confirmation popup implemented, modifiers replaced. Story says "quality" is also replaced but implementation only re-rolls modifiers, not rarity/quality. Logged in audit. |
| 6.1 | Score Active Cards | ✅ Aligned | Fantasy points calculated from Dota 2 match data; only active (locked roster snapshot) cards score; `WeeklyRosterEntry` ensures correct scoping. |
| 6.2 | Card Modifier Scoring | ✅ Aligned | Rarity bonus applied (configurable percentages via weights); card modifiers applied as additional multiplier. |
| 6.3 | Track Season Points | ✅ Aligned | Season points aggregated from all locked weeks, visible on My Team tab and season leaderboard. |
| 6.4 | Track Points per Card | ✅ Aligned | Per-card weekly points visible in roster view; historical tracking via week selector. |
| 6.5 | Prevent Duplicate Scoring | ✅ Aligned | Match data keyed by `match_id`; ingestion is idempotent (already-stored matches skipped). |
| 7.1 | Fetch Player Data | ✅ Aligned | `run_enrichment()` fetches player names and avatars; missing players handled gracefully (null avatar). |
| 7.2 | Import Match Data | ✅ Aligned | `ingest_league` fetches match stats (K/A/D, GPM, wards, tower damage); fantasy points calculated and stored per player-match. |
| 7.3 | Handle API Failures | ⚠️ Diverged | Errors are caught and printed in `_auto_ingest`; admin can re-trigger via `/ingest/league/{id}`. However, there's no explicit partial-ingestion rollback — errors are caught per league but not per match with transactional safety. |
| 7.4 | Auto-ingest on Startup | ✅ Aligned | `AUTO_INGEST_LEAGUES` env var parsed at startup; background thread runs ingestion; empty string disables it. |
| 8.1 | Season Leaderboard | ⚠️ Diverged | `/leaderboard/season` ranks users by cumulative points from locked weeks with rarity modifiers. However, the SQL does not use `week_override_id` — it only matches on `m.start_time BETWEEN wk.start_time AND wk.end_time`, missing matches with week overrides. |
| 8.2 | Scrollable Leaderboard | ✅ Aligned | Leaderboard tab is the default active tab; no login required to view it. |
| 8.3 | Show User Rank | ✅ Aligned | Logged-in user's row highlighted in gold on the leaderboard. |
| 8.4 | Weekly Leaderboard | ⚠️ Diverged | Weekly leaderboard mode exists with week selector. Same `week_override_id` omission as 8.1 in the SQL query. |
| 8.5 | Player Performance Browser | ✅ Aligned | Players tab lists all players with match count, avg/total points, filterable by name/team. Detail modal shows full match history with per-match stats. |
| 8.6 | Team Browser | ✅ Aligned | Teams tab lists teams with match/player count. Detail modal shows player roster with stats. |
| 9.1 | Generate Promo Codes | ✅ Aligned | Admin creates codes with token amount, codes are reusable across users, one use per user, admin can delete codes. |
| 9.2 | Grant Tokens | ✅ Aligned | Admin selects user, grants tokens, balance updates immediately, logged in audit with actor/target/amount. |
| 9.3 | Configure Scoring Weights | ⚠️ Diverged | Weights are stored in DB and displayed in admin tab, but the admin UI only shows weights as read-only — no edit functionality in the frontend. Story says editable from environment variables; implementation uses DB `Weight` table seeded from `seed_weights`. |
| 9.4 | Manage Season Lifecycle | ❓ Ambiguous | Story mentions admin can initiate/close a season with config via env vars. No explicit season start/close endpoint found. Season is implicitly managed via weeks and ingestion. |
| 9.5 | View System Status | ⚠️ Diverged | `/schedule/debug` shows schedule cache status but no general system status dashboard (ingest status, last ingest time, etc.) visible in admin UI. |
| 9.6 | Start New Season | ⚠️ Diverged | No explicit "start new season" button or endpoint. The migration code wipes weeks on schema change, but there's no admin-facing DB reset or new season workflow. |
| 9.7 | Admin Set Series Date | ⚠️ Diverged | `PUT /matches/{match_id}/week` and `/admin/sync-match-weeks` exist but operate at match level, not series level. No admin UI component for browsing series and assigning weeks — only API endpoints. Story says new datetime displayed on schedule; implementation overrides which week a match counts for, not the displayed datetime. |
| 9.8 | Recalculate Fantasy Points | ✅ Aligned | `/recalculate` applies current weights to all stored stats without re-fetching; returns count of records updated; logged in audit. |
| 9.9 | Manual League Ingestion | ✅ Aligned | Admin enters league ID, triggers ingestion which fetches matches, calculates points, seeds cards, enriches profiles; idempotent; logged. |
| 9.10 | Schedule Refresh | ✅ Aligned | `/schedule/refresh` busts cache, re-fetches from Google Sheets CSV, logged in audit. |
| 10.1 | Explain Scoring | ✅ Aligned | Collapsible "How is scoring calculated?" section on My Team tab lists all weighted stats. |
| 10.2 | Schedule Tab | ⚠️ Diverged | Schedule shows chronological series list with dates, team names (linked to modals), past results with scores, and stale cache notice. However, stream links only shown when present from sheet data — story says "stream link where available" which is met. Team names link to detail modals. Minor: no explicit "actual match start time" shown for past series when `series_result.start_time` is missing. |
| 11.1 | Server-side Validation | ✅ Aligned | All state-changing endpoints use `Depends(get_current_user)` or `Depends(require_admin)` which verify session server-side. |
| 11.2 | Audit Logs | ✅ Aligned | Tracks registrations, logins, draws, redemptions, admin grants, ingestion, recalculations, schedule refreshes, code creation/deletion. Each entry has timestamp, actor, action, detail. Admin-only access, most recent first. |
| 12.1 | Weight Calculation | ✅ Aligned | `POST /simulate/{match_id}` accepts per-stat weight overrides, merges with DB defaults, returns player fantasy points table. No auth required. |
| 12.2 | Weight Statistics Documentation | ✅ Aligned | `GET /simulate` returns machine-readable JSON documentation describing the endpoint, parameters, request/response format, and errors. |
| 13.1 | Twitch Integration - MVP Selection | 🔲 Not implemented | No Twitch integration, no MVP selection endpoint, no streamer access to match player lists. |
| 13.2 | Twitch Integration - Token Drops | 🔲 Not implemented | No streamer recognition, no drop mechanism, no Twitch viewer pool integration. |

## Key divergences

1. **5.1 — Free weekly token grant is not visibly implemented**: No code in `main.py` grants 1 token to all users on week lock; `auto_lock_weeks` logic is in the unseen `weeks.py` and may or may not include this. — *update implementation* (or verify `weeks.py` contains this logic).

2. **8.1 / 8.4 — Season and weekly leaderboard SQL ignores `week_override_id`**: The leaderboard queries only use `m.start_time BETWEEN wk.start_time AND wk.end_time` and omit the `OR m.week_override_id = wk.id` clause, so matches with admin week overrides are excluded from rankings. — *update implementation*.

3. **9.3 — Scoring weights are read-only in admin UI**: The admin tab displays weights but provides no editing interface; weights can only be changed by modifying the DB or environment variables and reseeding. Story implies they should be editable. — *update implementation* or *clarify story* (env-only may be acceptable for POC).

4. **9.6 — No "Start New Season" workflow**: There is no admin endpoint or UI to reset the database and begin a fresh season. The migration code handles schema changes but is not a user-facing season reset. — *update implementation*.

5. **9.7 / 4.3 — Series date override works at match level, not series level, and lacks admin UI**: The API overrides the fantasy week for individual matches, not series. No admin frontend component exists to browse series or set corrected dates. The overridden datetime is not displayed on the schedule. — *update implementation*.

6. **5.5 — Re-roll does not replace card "quality"**: Story says "Modifiers and quality replaced" but implementation only re-rolls stat modifiers, not the card's rarity. — *clarify story* (does "quality" mean rarity, or is it a separate attribute?).

7. **9.5 — System status view is minimal**: Only a schedule debug endpoint exists; no dashboard showing ingest status, last run time, background thread health, or general system state. — *update implementation*.

8. **13.1 / 13.2 — Twitch integration entirely missing**: No MVP selection, no streamer authentication, no token drop mechanism for stream viewers. — *update implementation* (if in scope for this phase).
