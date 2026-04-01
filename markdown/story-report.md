<!-- Generated automatically by scripts/story_report.py — do not edit by hand -->
_Last updated: 2026-04-01 15:00 UTC_

# Story Coverage Report

| ID | Story | Status | Notes |
|----|-------|--------|-------|
| 1.1 | User Registration | ✅ Aligned | Registration validates unique username/email, grants initial tokens, records `created_at` timestamp, and creates the account. |
| 1.2 | User Login | ✅ Aligned | Login validates username + password, returns error on invalid credentials, uses session middleware. Logged-out users get 401 on protected endpoints. |
| 1.3 | User Receive Temporary Password | ⚠️ Diverged | Backend sends temp password via email and sets `must_change_password`. However, if the user has no email the endpoint returns 200 silently instead of showing an error informing them of the inability to reset. |
| 1.4 | User Password Reset | ✅ Aligned | `PUT /profile/password` requires current password before accepting a new one. Available on the Profile tab. |
| 1.5 | User Logout | ✅ Aligned | `POST /logout` clears session. Logout button visible on all pages via the header. |
| 1.6 | Admin-only Access | ✅ Aligned | Admin tab hidden for non-admins in UI. `require_admin` dependency re-verifies `is_admin` from session on every admin endpoint (server-side check). |
| 1.7 | User Profile Tab | ✅ Aligned | Username change (unique enforced), password change with current-password check, optional OpenDota player ID link with name/avatar preview all implemented. |
| 2.1 | Grant Starter Tokens on Registration | ✅ Aligned | `INITIAL_TOKENS` env var configures the count; tokens set at registration time. |
| 2.2 | Token Visibility | ✅ Aligned | Token balance shown in header (`tokenBalance` element) across all tabs; updated after draw, redeem, and grant events. `drawCounter` on My Team tab stays in sync. |
| 2.3 | View Cards | ✅ Aligned | Drawn cards display player name, avatar, rarity, and current week's points. Bench/active distinction is clear in My Team tab. |
| 2.4 | View Weekly Rosters | ✅ Aligned | Upcoming week's roster is the default view. Lock date is displayed. Empty active slots rendered explicitly with "— empty slot —" rows. |
| 2.5 | View Current and Season Points | ✅ Aligned | Weekly and season points shown separately in My Team tab. Week history selector allows viewing past weeks. New user with no cards would show 0. |
| 3.1 | Generate Cards | ✅ Aligned | Admin triggers ingestion with league ID; `seed_cards` generates cards per player (1 legendary, 2 epic, 4 rare, 8 common as configured in `seed.py`). Shared deck, idempotent seeding implied by unclaimed pool logic. |
| 3.2 | Card Drawing | ✅ Aligned | Requires ≥1 token; card shown in reveal modal; auto-placed in active roster if slots available, otherwise bench. Prefers players user doesn't own; allows duplicates only when all players owned. |
| 3.3 | Remove Cards from Pool | 🔲 Not implemented | Marked post-MVP; no admin endpoint to remove a player and refund tokens. Expected. |
| 3.4 | Card Rarity | ✅ Aligned | Rarity (card_type) is set at deck creation time, not draw time. Shown in reveal modal and roster views via CSS badge. |
| 3.5 | Assign Randomized Modifiers | 🔲 Not implemented | No `modifiers` column on the `cards` table. Cards have no modifiers stored or displayed. |
| 3.6 | Modifier Management | 🔲 Not implemented | No modifier management UI or backend. Rarity modifier percentages exist but per-card modifiers (story 3.5) do not. |
| 3.7 | View Seasonal Reserve Cards | ✅ Aligned | Bench cards shown in My Team tab with player, rarity, and week points. Bench hidden for locked past weeks (read-only snapshot). |
| 3.8 | View Permanent Collection | 🔲 Not implemented | Marked post-MVP. No cross-season collection view. Expected. |
| 4.1 | Place Cards into Active Slots | ✅ Aligned | 5 slots enforced. Activate/Bench (deactivate) endpoints exist. Duplicate player check prevents two cards for same player active. Changes only on editable week (locked weeks show snapshot). |
| 4.2 | Lock Active Cards | ⚠️ Diverged | Auto-lock runs via background thread (`auto_lock_weeks`). UI shows locked banner and lock date. However, the lock boundary is based on `week.start_time` (Monday) via `auto_lock_weeks`, not "Sunday at end of day (UTC)" as the story specifies — need to verify `weeks.py` logic. |
| 4.3 | Admin Move Series Time Manually | 🔲 Not implemented | No admin endpoint to view series or override a series date. `schedule.py` handles display but no series-date override API exists. |
| 4.4 | Preserve Points | ✅ Aligned | Points stored via `player_match_stats` and `weekly_roster_entries` in DB. Season total derived from past week records. |
| 4.5 | View Past Week Snapshots | ✅ Aligned | Week selector dropdown lists all weeks. Selecting a locked week returns immutable snapshot with week-scoped points. Current editable week always accessible. |
| 5.1 | Free Weekly Token | ⚠️ Diverged | `auto_lock_weeks` in `weeks.py` is referenced but not shown in the codebase provided; it's unclear if it grants tokens on lock. No visible token-grant-on-lock logic in `main.py`. |
| 5.2 | Token Log (admin) | ⚠️ Diverged | Audit log tracks draws, redemptions, and admin grants individually, but there is no aggregated view of weekly free token grants showing "total number of users affected." Token log is not a separate view — it's merged into the general audit log. |
| 5.3 | Spend Token to Draw Card | ✅ Aligned | 1 token deducted, card assigned to user, duplicate-player prevention in place, card shown in reveal modal. |
| 5.4 | Redeem Code | ✅ Aligned | Valid code grants tokens; invalid code returns error; one use per user enforced via `CodeRedemption`; logged in audit log. |
| 5.5 | Re-roll Modifiers | 🔲 Not implemented | No re-roll endpoint or UI. Depends on modifiers (3.5) which are also not implemented. |
| 6.1 | Score Active Cards | ✅ Aligned | Scoring uses Dota 2 match data; only locked-week roster entries count; match uniqueness via `match_id` primary key prevents double counting. |
| 6.2 | Card Modifier Scoring | ⚠️ Diverged | Rarity bonus is applied (common +0%, rare +1%, etc.) and is configurable via admin weights. However, story 3.5 per-card modifiers are not implemented, so only the rarity multiplier portion works. |
| 6.3 | Track Season Points | ✅ Aligned | Season points calculated across all locked weeks with rarity modifiers. Visible in My Team tab and season leaderboard. |
| 6.4 | Track Points per Card | ✅ Aligned | Per-week card point contribution visible in roster view. Week selector enables historical tracking. |
| 6.5 | Prevent Duplicate Scoring | ✅ Aligned | `match_id` is a primary key; ingestion is idempotent (re-ingestion skips existing matches). |
| 7.1 | Fetch Player Data | ✅ Aligned | `run_enrichment()` fetches player names and avatars from OpenDota. Missing players handled gracefully (name/avatar may be null). |
| 7.2 | Import Match Data | ✅ Aligned | `PlayerMatchStats` stores kills, assists, deaths, GPM, wards (obs+sen), tower damage. Fantasy points calculated and stored per player-match. |
| 7.3 | Handle API Failures | ⚠️ Diverged | Failures are caught and printed (`print(f"[AUTO-INGEST] ... failed: {e}")`), but not logged to the audit log. Partial ingestion safety depends on `ingest.py` implementation (not shown). Admin can re-trigger via endpoint. |
| 7.4 | Auto-ingest on Startup | ⚠️ Diverged | Auto-ingest runs on startup via executor. However, `AUTO_INGEST_LEAGUES` defaults to `"19368,19369"` instead of empty, meaning auto-ingest is ON by default. Story says `AUTO_INGEST_LEAGUES=` (empty) should disable it — the code handles empty correctly, but the default is non-empty. |
| 8.1 | Season Leaderboard | ✅ Aligned | Users ranked by cumulative fantasy points across locked weeks with rarity modifiers applied. Only active roster snapshots counted. |
| 8.2 | Scrollable Leaderboard | ✅ Aligned | Leaderboard tab is visible and accessible without login (no auth check on `/leaderboard/season` endpoint or the UI tab). |
| 8.3 | Show User Rank | ✅ Aligned | Logged-in user's row highlighted with gold color and bold text on the season/weekly leaderboard. |
| 8.4 | Weekly Leaderboard | ✅ Aligned | Weekly mode with week selector available alongside season view. Shows locked weeks. |
| 8.5 | Player Performance Browser | ✅ Aligned | Players tab lists all players with matches, avg/total points. Filterable by name/team. Player detail modal shows full match history with K/A/D, GPM, wards, tower damage, fantasy points. |
| 8.6 | Team Browser | ✅ Aligned | Teams tab lists teams with match count and player count. Team detail modal shows player roster with stats. |
| 9.1 | Generate Promo Codes | ✅ Aligned | Admin creates codes with configurable token amount. Codes are reusable (multiple users). Each user can redeem once. Admin can delete codes. |
| 9.2 | Grant Tokens | ✅ Aligned | Admin selects user and grants tokens. Balance updates immediately. Logged in audit log with admin actor, target user, and amount. |
| 9.3 | Configure Scoring Weights | ✅ Aligned | Stat weights and rarity modifier percentages editable from admin tab. Changes take effect for future calculations; recalculate button available separately. |
| 9.4 | Manage Season Lifecycle | ⚠️ Diverged | No explicit "initiate" or "close season" UI/endpoint in admin. Season config (lock dates, league IDs) managed via env vars. Week generation is automatic, but there's no season start/end ceremony. |
| 9.5 | View System Status | 🔲 Not implemented | No system status dashboard (ingest status, schedule cache status) in admin tab. Only a `/schedule/debug` endpoint exists but it's not surfaced in the UI. |
| 9.6 | Start New Season | 🔲 Not implemented | No "reset database and begin new season" functionality in the admin UI or backend. |
| 9.7 | Admin Set Series Date | 🔲 Not implemented | No endpoint or UI to select a series and override its week/date. Same gap as 4.3. |
| 9.8 | Recalculate Fantasy Points | ✅ Aligned | Recalculate button applies current weights to all stored stats without re-fetching. Returns record count. Logged in audit log. |
| 9.9 | Manual League Ingestion | ✅ Aligned | Admin enters league ID, triggers ingestion. Fetches matches, calculates points, seeds cards, enriches profiles. Idempotent. Logged. |
| 9.10 | Schedule Refresh | ✅ Aligned | Refresh button busts in-memory cache, fetches fresh data from Google Sheets URL. Logged in audit log. |
| 10.1 | Explain Scoring | ✅ Aligned | Collapsible "How is scoring calculated?" section in My Team tab lists all weighted stats. |
| 10.2 | Schedule Tab | ⚠️ Diverged | All series shown chronologically with date, team names, and stream links. Past series show result (e.g. 2–0). Team names link to team modal. Stale cache notice implemented. However, team name links rely on `team1_id`/`team2_id` from schedule data — if those aren't populated, links won't render. Also, the schedule module `get_schedule` implementation isn't shown, so division-spanning and complete coverage can't be fully verified. |
| 11.1 | Server-side Validation | ✅ Aligned | All state-changing actions validated server-side. Admin endpoints use `require_admin` which checks session, not just client flag. |
| 11.2 | Audit Logs | ⚠️ Diverged | Tracks: registrations, logins, draws, redemptions, admin grants, ingestion, weight changes, recalculations, schedule refreshes, code creation/deletion. Each entry has timestamp, actor, action, detail. Admin-only, most recent first. However, roster changes are not tracked (which aligns with the story), but **user login** logging is present while the story doesn't explicitly require it (acceptable). Missing: no explicit log entry for the weekly token grant event. |

## Key divergences

1. **Story 3.5 / 3.6 — Card modifiers not implemented**: Cards have no `modifiers` column or randomized modifier assignment; modifier management and display are entirely absent. → **Update implementation.**

2. **Story 5.5 — Re-roll modifiers not implemented**: No re-roll endpoint or UI exists, blocked by the missing modifier system (3.5). → **Update implementation** (after 3.5).

3. **Story 9.7 / 4.3 — Admin series date override not implemented**: No way for admins to view series, select one, and override its date/week. This is a core admin correction feature. → **Update implementation.**

4. **Story 9.6 — Start new season not implemented**: No mechanism to reset the database and begin a fresh season from the admin panel. → **Update implementation.**

5. **Story 9.5 — System status dashboard not implemented**: Admin has no view of ingest status or schedule cache health; the `/schedule/debug` endpoint exists but isn't exposed in the UI. → **Update implementation.**

6. **Story 5.1 — Free weekly token grant unclear**: The token-grant-on-lock logic is not visible in the provided code (`auto_lock_weeks` is imported but its implementation is not shown); if it doesn't grant tokens, all users miss their weekly free token. → **Update implementation** (verify `weeks.py` and add if missing).

7. **Story 1.3 — Forgot password silent on missing email**: The endpoint returns HTTP 200 even when the user has no email, instead of showing an error as required by the acceptance criteria. → **Update implementation** to return an error when the user exists but has no email.

8. **Story 7.4 — Auto-ingest default is non-empty**: `AUTO_INGEST_LEAGUES` defaults to `"19368,19369"`, meaning auto-ingest runs by default. The story implies the default should be disabled (empty). → **Clarify story** or **update implementation** to default to empty.

9. **Story 9.4 — Season lifecycle management incomplete**: No explicit season initiation or closure workflow exists; week generation is automatic but there's no admin-facing season start/end control. → **Update implementation.**

10. **Story 6.2 — Card modifier scoring partial**: Only rarity bonus is applied; the per-card modifier component from story 3.5 is missing, so the full modifier scoring pipeline described across 3.5/3.6/6.2 is incomplete. → **Update implementation** (dependent on 3.5).
