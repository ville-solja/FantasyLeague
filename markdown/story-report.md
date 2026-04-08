<!-- Generated automatically by scripts/story_report.py — do not edit by hand -->
_Last updated: 2026-04-08 14:35 UTC_

# Story Coverage Report

| ID | Story | Status | Notes |
|----|-------|--------|-------|
| 1.1 | User Registration | ✅ Aligned | Registration with unique email/username, initial tokens, and timestamp all implemented in `/register`. |
| 1.2 | User Login | ✅ Aligned | Login via username+password, error on invalid creds, session-based auth, and route guards present. |
| 1.3 | User Receive Temporary Password | ✅ Aligned | `/forgot-password` sends temp password to email; returns 200 regardless to avoid enumeration; sets `must_change_password` flag. |
| 1.4 | User Password Reset | ✅ Aligned | `/profile/password` requires current password before accepting a new one; clears `must_change_password`. |
| 1.5 | User Logout | ✅ Aligned | `/logout` clears session; logout button visible on all pages via header. |
| 1.6 | Admin-only Access | ✅ Aligned | `require_admin` dependency checks `is_admin` from session server-side; admin tab hidden for non-admins in frontend. |
| 1.7 | User Profile Tab | ✅ Aligned | Username change (uniqueness enforced), password change with current-password verification, optional OpenDota player ID with preview. |
| 2.1 | Grant Starter Tokens on Registration | ✅ Aligned | `INITIAL_TOKENS` env var used; tokens set on user creation. |
| 2.2 | Token Visibility | ✅ Aligned | Token balance in header (`tokenBalance`), updated after draw/redeem/grant; synced with My Team counter. |
| 2.3 | View Cards | ✅ Aligned | Drawn cards display player name, rarity, and week points; bench vs active distinction shown in My Team tab. |
| 2.4 | View Weekly Rosters | ✅ Aligned | Default view shows upcoming week roster; lock date displayed; empty active slots rendered explicitly. |
| 2.5 | View Current and Season Points | ✅ Aligned | Weekly and season points shown separately in My Team tab; week selector allows viewing past weeks; new user starts at 0. |
| 3.1 | Generate Cards | ⚠️ Diverged | `seed_cards` is called during ingestion, but the code for it is in `seed.py` which is not provided — cannot verify deck composition (1 legendary, 2 epic, 4 rare, 8 common per player) or idempotency. |
| 3.2 | Card Drawing | ✅ Aligned | Token check, reveal modal, auto-placement to active/bench, preference for un-owned players with duplicate fallback. |
| 3.3 | Remove Cards from Pool | 🔲 Not implemented | Marked post-MVP; no admin endpoint to remove a player's cards and refund tokens. |
| 3.4 | Card Rarity | ✅ Aligned | Rarity set at deck creation (card_type column); shown in reveal modal and roster views. |
| 3.5 | Assign Randomized Modifiers | ✅ Aligned | `_assign_modifiers` assigns random stat modifiers at draw time; stored in `card_modifiers` table; visible on card. |
| 3.6 | Modifier Management | ⚠️ Diverged | Modifier weights (count per rarity, bonus_pct) are in the `weights` DB table seeded from `seed_weights`, not purely from environment variables as story requires. Recalculate does not recompute card modifier effects retroactively. |
| 3.7 | View Seasonal Reserve Cards | ✅ Aligned | Bench shown in My Team tab with player/rarity/points; bench hidden for locked past weeks (snapshot view). |
| 3.8 | View Permanent Collection | 🔲 Not implemented | Post-MVP; no cross-season collection feature. |
| 4.1 | Place Cards into Active Slots | ✅ Aligned | 5-slot limit enforced; activate/deactivate endpoints; duplicate player check; changes only on current/upcoming week. |
| 4.2 | Lock Active Cards | ⚠️ Diverged | `auto_lock_weeks` runs periodically, but locking logic is in `weeks.py` (not provided). Frontend shows lock banner and date. Story says "every Sunday end of day UTC" — cannot confirm exact timing without `weeks.py`. |
| 4.3 | Admin Move Series Time Manually | ⚠️ Diverged | `PUT /matches/{match_id}/week` overrides week assignment per match, not per series. Story says "select a series" but implementation operates on individual matches. The `sync-match-weeks` endpoint does batch matching. |
| 4.4 | Preserve Points | ✅ Aligned | `weekly_roster_entries` table stores locked week snapshots; season points derived from past week records. |
| 4.5 | View Past Week Snapshots | ✅ Aligned | Week selector dropdown; past locked weeks show immutable snapshot; weekly points scoped to that week's matches. |
| 5.1 | Free Weekly Token | ⚠️ Diverged | No code in `main.py` grants a free token on week lock. The `auto_lock_weeks` function is in `weeks.py` (not provided), so it may be there, but it is unverifiable from the provided codebase. |
| 5.2 | Token Log (admin) | ⚠️ Diverged | Audit log tracks admin grants, draws, and redemptions, but there is no dedicated view summarising weekly free token grants with user counts. Token events are mixed into the general audit log. |
| 5.3 | Spend Token to Draw Card | ✅ Aligned | 1 token deducted; card owned by user; duplicate-player prevention; reveal modal shown. |
| 5.4 | Redeem Code | ✅ Aligned | Valid code grants tokens; invalid shows error; one use per user; logged in audit log. |
| 5.5 | Re-roll Modifiers | ✅ Aligned | Costs 1 token; confirmation popup in UI; modifiers replaced; logged in audit. Story says "quality replaced" — rarity is not changed on reroll, only modifiers. |
| 6.1 | Score Active Cards | ✅ Aligned | Points calculated from Dota 2 match data; only locked (snapshotted) active cards score; match uniqueness via `player_match_stats`. |
| 6.2 | Card Modifier Scoring | ✅ Aligned | Rarity bonus applied (configurable defaults: common +0%, rare +1%, epic +2%, legendary +3%); card stat modifiers also applied. |
| 6.3 | Track Season Points | ✅ Aligned | Season points aggregated from all locked weeks; visible in My Team tab and season leaderboard. |
| 6.4 | Track Points per Card | ✅ Aligned | Per-card week points shown in roster view; week selector enables historical tracking. |
| 6.5 | Prevent Duplicate Scoring | ✅ Aligned | `player_match_stats` keyed by player+match; ingestion is idempotent (already-stored matches skipped). |
| 7.1 | Fetch Player Data | ✅ Aligned | `run_enrichment()` called after ingestion; player names and avatars fetched. Graceful handling implied by enrichment pattern. |
| 7.2 | Import Match Data | ✅ Aligned | `ingest_league` fetches match data; `PlayerMatchStats` stores kills, assists, deaths, GPM, wards, tower damage; fantasy points calculated. |
| 7.3 | Handle API Failures | ✅ Aligned | Ingestion wrapped in try/except with logging; admin can re-trigger via `/ingest/league/{id}`; partial ingestion doesn't corrupt (idempotent). |
| 7.4 | Auto-ingest on Startup | ✅ Aligned | `AUTO_INGEST_LEAGUES` env var parsed; background thread runs `_ingest_poll_loop`; empty value results in no thread started. |
| 8.1 | Season Leaderboard | ✅ Aligned | `/leaderboard/season` ranks users by cumulative fantasy points from locked weeks' active roster snapshots with rarity modifiers. |
| 8.2 | Scrollable Leaderboard | ✅ Aligned | Leaderboard tab visible without login; no auth required for `/leaderboard/season` or `/leaderboard/weekly` endpoints. |
| 8.3 | Show User Rank | ✅ Aligned | Frontend highlights logged-in user's row in leaderboard with gold color/bold. |
| 8.4 | Weekly Leaderboard | ✅ Aligned | Weekly mode with week selector available alongside season view. |
| 8.5 | Player Performance Browser | ✅ Aligned | Players tab lists all players with match count, avg/total points; filterable by name/team; detail modal shows full match history with per-match stats. |
| 8.6 | Team Browser | ✅ Aligned | Teams tab lists teams with match/player count; detail modal shows player roster with stats. |
| 9.1 | Generate Promo Codes | ✅ Aligned | Admin creates codes with token amount; codes are reusable (multi-user); one redemption per user; admin can delete codes. |
| 9.2 | Grant Tokens | ✅ Aligned | Admin selects user, grants tokens; balance updates; logged in audit with actor, target, amount. |
| 9.3 | Configure Scoring Weights | ⚠️ Diverged | Weights are stored in DB and displayed in admin tab, but they are not editable from the admin UI — only viewable. Story says "editable from environment variables"; `seed_weights` seeds them but admin cannot modify via UI. |
| 9.4 | Manage Season Lifecycle | ❓ Ambiguous | No explicit "close season" endpoint. Season config via env vars is partially present. Story is vague on what "initiate and close" entails. |
| 9.5 | View System Status | ⚠️ Diverged | `/schedule/debug` shows schedule URL status, but there is no comprehensive system status view showing ingest status or general health in the admin tab UI. |
| 9.6 | Start New Season | ⚠️ Diverged | No "reset database and begin new season" endpoint or UI. The migration code wipes weeks on schema change but there is no admin-triggered season reset. |
| 9.7 | Admin Set Series Date | ⚠️ Diverged | `PUT /matches/{match_id}/week` reassigns a match to a different week, but there is no admin UI for selecting a series from a list and setting its week. The `sync-match-weeks` endpoint auto-assigns but is not user-driven series selection. |
| 9.8 | Recalculate Fantasy Points | ✅ Aligned | `/recalculate` applies current weights to all stored stats; returns count; logged in audit. Does not re-fetch from OpenDota. |
| 9.9 | Manual League Ingestion | ✅ Aligned | Admin enters league ID and triggers ingestion; fetches matches, calculates points, seeds cards, enriches profiles; idempotent; logged. |
| 9.10 | Schedule Refresh | ✅ Aligned | Refresh button busts cache; re-fetches from Google Sheets CSV; logged in audit. |
| 10.1 | Explain Scoring | ✅ Aligned | Collapsible "How is scoring calculated?" section in My Team tab lists weighted stats formula. |
| 10.2 | Schedule Tab | ✅ Aligned | Chronological list with past results (scores, times) and upcoming fixtures (dates, teams, stream links); team names link to modals; stale cache notice shown. |
| 11.1 | Server-side Validation | ✅ Aligned | All state-changing endpoints use `Depends(get_current_user)` or `Depends(require_admin)`; admin verified from session server-side. |
| 11.2 | Audit Logs | ✅ Aligned | Tracks registrations, logins, draws, redemptions, admin grants, ingestion, recalculations, schedule refreshes, code creation/deletion; timestamp, actor, action, detail; admin-only; most recent first. |
| 12.1 | Weight Calculation | ✅ Aligned | `POST /simulate/{match_id}` accepts custom stat weights, merges with DB defaults, returns player fantasy scores table for the match. No auth required. |
| 12.2 | Weight Statistics Documentation | ✅ Aligned | `GET /simulate` returns structured JSON documentation describing the endpoint, parameters, request body, response format, and errors. |
| 13.1 | Twitch Integration – MVP Selection | 🔲 Not implemented | No Twitch integration, no MVP selection endpoint, no streamer access to match player lists. |
| 13.2 | Twitch Integration – Token Drops | 🔲 Not implemented | No streamer recognition, no drop mechanism, no watcher/player pool integration. |

## Key divergences

1. **9.6 — No "Start New Season" feature**: There is no admin endpoint or UI to reset the database and begin a fresh season; the story requires an explicit reset flow. → **update implementation**

2. **9.7 — Series-level week override missing from admin UI**: The backend operates on individual match IDs, but the story requires selecting a series from a visible list and assigning it to a week. No admin UI exists for this. → **update implementation**

3. **5.1 — Free weekly token grant unverifiable**: The weekly token grant on lock is not in `main.py`; it may exist in the unprovided `weeks.py`, but there's no evidence it awards 1 token to all users. → **clarify story** or verify `weeks.py` implementation

4. **9.3 — Scoring weights not editable in admin UI**: Weights are displayed read-only in the admin panel. The story says they should be "editable from environment variables" — neither runtime editing nor env-var-based editing flow is available in the UI. → **clarify story** (env-only vs UI-editable) and potentially **update implementation**

5. **9.5 — System status view incomplete**: Only schedule debug info is available; no view of ingest status, background thread health, or general system state as the story requires. → **update implementation**

6. **5.2 — Token log lacks structured weekly grant summary**: Token events are in the generic audit log but there is no view that shows weekly free token grants with "total number of users affected" as specified. → **update implementation**

7. **3.1 — Card deck composition unverifiable**: `seed_cards` is imported from `seed.py` which is not provided; cannot confirm the required 1/2/4/8 rarity distribution per player or idempotency. → **provide `seed.py` for audit** or **update implementation**

8. **13.1 & 13.2 — Twitch integration entirely absent**: No streamer authentication, MVP selection, or token drop functionality exists anywhere in the codebase. → **update implementation** (or defer if post-MVP)

9. **9.4 — Season lifecycle management ambiguous**: No explicit "close season" action exists; story is vague on what initiate/close means beyond env config. → **clarify story** to define concrete actions, then **update implementation**

10. **5.5 / Re-roll — "Quality" not replaced**: Story says "Modifiers and quality replaced" but reroll only replaces modifiers; card rarity (quality) is unchanged. → **clarify story** (is rarity intended to change?) or **update implementation**
