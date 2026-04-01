<!-- Generated automatically by scripts/story_report.py — do not edit by hand -->
_Last updated: 2026-04-01 16:44 UTC_

# Story Coverage Report

| ID | Story | Status | Notes |
|----|-------|--------|-------|
| 1.1 | User Registration | ✅ Aligned | Registration validates unique username/email, grants initial tokens, records `created_at` timestamp, and creates the account. |
| 1.2 | User Login | ✅ Aligned | Login with username+password, error on invalid credentials, session-based auth, unauthenticated users redirected to leaderboard. |
| 1.3 | User Receive Temporary Password | ✅ Aligned | `/forgot-password` endpoint generates temp password, emails it, sets `must_change_password` flag. Returns 200 regardless to avoid enumeration. Story says "if the user does not have an email, an error is given" — backend silently returns OK instead. |
| 1.4 | User Password Reset | ✅ Aligned | Profile tab has current+new password form via `PUT /profile/password`. Requires current password. |
| 1.5 | User Logout | ✅ Aligned | `POST /logout` clears session; logout button visible on all pages via header. |
| 1.6 | Admin-only Access | ✅ Aligned | Admin tab hidden for non-admins, `require_admin` dependency re-checks `is_admin` from session on every admin endpoint. However, `is_admin` is read from session set at login — not re-queried from DB on each request. |
| 1.7 | User Profile Tab | ✅ Aligned | Username change (unique enforced), password change, OpenDota player ID link with preview when player exists in league data. |
| 2.1 | Grant Starter Tokens on Registration | ✅ Aligned | `INITIAL_TOKENS` env var used, tokens set at registration. |
| 2.2 | Token Visibility | ✅ Aligned | Token balance shown in header (`#tokenBalance`), updated after draw/redeem, `drawCounter` on My Team tab syncs. |
| 2.3 | View Cards | ⚠️ Diverged | Cards show player name, rarity, and week points. However, cards show `total_points` for the scoped week, not explicitly "current week's points" — if viewing a past week the points reflect that week. Bench is visible on My Team tab. |
| 2.4 | View Weekly Rosters | ✅ Aligned | Upcoming week's roster is the default view, lock date shown via `rosterWeekStatus`, empty active slots rendered explicitly. |
| 2.5 | View Current and Season Points | ✅ Aligned | Weekly and season points displayed on My Team tab. Week selector allows viewing past weeks. New user with no activity shows 0. |
| 3.1 | Generate Cards | ⚠️ Diverged | Admin can ingest a league ID which calls `seed_cards(league_id)`. Idempotency and shared deck are handled. Per-player rarity distribution (1 legendary, 2 epic, 4 rare, 8 common) depends on `seed.py` which is not provided — cannot fully verify. |
| 3.2 | Card Drawing | ✅ Aligned | Draws cost 1 token, reveal modal shown, card goes to active roster if slots exist else bench. Prefers unowned players, allows duplicates only when all players owned. |
| 3.3 | Remove Cards from Pool | 🔲 Not implemented | Marked post-MVP; no endpoint or UI for removing players/cards from pool. |
| 3.4 | Card Rarity | ✅ Aligned | Rarity set at deck creation time (in `seed_cards`), displayed in reveal modal and roster views. |
| 3.5 | Assign Randomized Modifiers | ✅ Aligned | `_assign_modifiers` randomly assigns stat modifiers at draw time based on rarity config. Stored in `card_modifiers` table. Visible in roster and card views. |
| 3.6 | Modifier Management | ⚠️ Diverged | Modifier weights (`modifier_count_*`, `modifier_bonus_pct`) are editable via the generic weights admin UI. However, the story says "modifier changes are not applied retroactively without an explicit recalculate action" — the recalculate endpoint recalculates `fantasy_points` on `PlayerMatchStats` but does not re-roll card modifiers, which is correct. Rarity modifier % changes are reflected immediately in scoring queries (no recalc needed for display), which may diverge from the intent. |
| 3.7 | View Seasonal Reserve Cards | ✅ Aligned | Bench shown on My Team tab with player, rarity, and week points. Bench hidden for locked past weeks (snapshot view). |
| 3.8 | View Permanent Collection | 🔲 Not implemented | Marked post-MVP; no cross-season collection feature. |
| 4.1 | Place Cards into Active Slots | ✅ Aligned | 5 active slots, activate/deactivate endpoints, duplicate player check enforced server-side. No explicit check preventing changes to locked weeks in activate/deactivate endpoints — only the live card's `is_active` flag is toggled. |
| 4.2 | Lock Active Cards | ⚠️ Diverged | Weeks are auto-locked by `auto_lock_weeks` in background thread. UI shows locked banner and lock date. However, the story says "auto-lock every Sunday at end of day (UTC)" — the implementation locks based on `start_time` of the week (lock before matches start), not Sunday EOD. The activate/deactivate endpoints do not check whether the current week is locked before allowing changes. |
| 4.3 | Admin Move Series Time Manually | ⚠️ Diverged | Story requires ability to see series in admin tab and set corrected date that persists across re-ingestions. No admin UI or endpoint for editing series/match dates exists in the codebase. The `Admin Set Series Date` (9.7) reiterates this. |
| 4.4 | Preserve Points | ✅ Aligned | Weekly roster snapshots stored in `weekly_roster_entries`; season points derived from past week records. |
| 4.5 | View Past Week Snapshots | ✅ Aligned | Week selector dropdown, locked weeks show immutable snapshot, points scoped to that week's time range. |
| 5.1 | Free Weekly Token | ⚠️ Diverged | Story says "when the week is locked all users are granted 1 additional token." The `auto_lock_weeks` function (in `weeks.py`, not provided) presumably handles this, but it is not visible in the provided codebase. No token grant logic is visible in `main.py` when weeks lock. |
| 5.2 | Token Log (admin) | ⚠️ Diverged | Audit log tracks `admin_grant_tokens`, `token_draw`, `token_redeem`. However, weekly free token grants are not explicitly logged with "total number of users affected" as required. The audit log is a generic list, not a dedicated token log view. |
| 5.3 | Spend Token to Draw Card | ✅ Aligned | 1 token deducted, card owned by user, duplicate player prevention, reveal modal shown. |
| 5.4 | Redeem Code | ✅ Aligned | Valid code grants tokens, invalid shows error, one use per user enforced, logged in audit log. |
| 5.5 | Re-roll Modifiers | 🔲 Not implemented | No endpoint or UI for spending a token to re-roll a card's modifiers and quality. |
| 6.1 | Score Active Cards | ✅ Aligned | Scoring uses match data, only locked-week roster snapshots count, unique match tracking via `player_match_stats`. |
| 6.2 | Card Modifier Scoring | ✅ Aligned | Rarity bonus applied (configurable percentages). Card stat modifiers also applied as average bonus. |
| 6.3 | Track Season Points | ✅ Aligned | Season points calculated from all locked weeks, visible on My Team tab and season leaderboard. |
| 6.4 | Track Points per Card | ✅ Aligned | Per-card `total_points` shown in roster view, historical via week selector. |
| 6.5 | Prevent Duplicate Scoring | ✅ Aligned | `player_match_stats` keyed by player+match; ingestion is idempotent (already-stored matches skipped). |
| 7.1 | Fetch Player Data | ✅ Aligned | `run_enrichment()` fetches player names/avatars from OpenDota. Missing players handled gracefully (avatar hidden on error). |
| 7.2 | Import Match Data | ✅ Aligned | `ingest_league` fetches match data; `PlayerMatchStats` stores kills, assists, deaths, GPM, wards, tower damage; fantasy points calculated and stored. |
| 7.3 | Handle API Failures | ⚠️ Diverged | Auto-ingest catches and prints exceptions but there is no structured logging. Admin can re-trigger via the ingest endpoint. Partial ingestion safety depends on `ingest.py` (not provided). |
| 7.4 | Auto-ingest on Startup | ✅ Aligned | `AUTO_INGEST_LEAGUES` env var parsed, runs in background thread via `ThreadPoolExecutor`, empty value disables auto-ingest (`.isdigit()` filter). |
| 8.1 | Season Leaderboard | ✅ Aligned | Users ranked by cumulative fantasy points across locked weeks with rarity modifiers applied. |
| 8.2 | Scrollable Leaderboard | ✅ Aligned | Leaderboard tab is the default active tab, visible without login. |
| 8.3 | Show User Rank | ✅ Aligned | Logged-in user's row highlighted with gold color and bold text in leaderboard. |
| 8.4 | Weekly Leaderboard | ✅ Aligned | Weekly mode with week selector available alongside season view. |
| 8.5 | Player Performance Browser | ✅ Aligned | Players tab lists all players with match count, avg/total points. Filterable by name/team. Player detail modal shows full match history with K/A/D, GPM, wards, tower damage, fantasy points. |
| 8.6 | Team Browser | ✅ Aligned | Teams tab lists teams with match count and player count. Team detail modal shows roster with stats. |
| 9.1 | Generate Promo Codes | ✅ Aligned | Admin creates codes with token amount, codes are reusable (multiple users), one redemption per user, admin can delete codes. |
| 9.2 | Grant Tokens | ✅ Aligned | Admin selects user, grants tokens, balance updates, logged with actor/target/amount. |
| 9.3 | Configure Scoring Weights | ✅ Aligned | All stat weights editable from admin tab. Rarity modifier percentages also configurable. Recalculate button available separately. |
| 9.4 | Manage Season Lifecycle | ⚠️ Diverged | No explicit "initiate season" or "close season" UI/endpoint. Season configuration is via env vars. Week generation is automatic. |
| 9.5 | View System Status | ⚠️ Diverged | `/schedule/debug` endpoint exists (admin-only) showing schedule URL status. No general system status dashboard showing ingest status or cache status in the admin UI. |
| 9.6 | Start New Season | ⚠️ Diverged | No "reset database and begin new season" button or endpoint. The migration logic wipes weeks on structure change, but this is not a user-facing season reset. |
| 9.7 | Admin Set Series Date | 🔲 Not implemented | No endpoint or UI for selecting a series and overriding its week/date. No `override_date` or similar column on matches. |
| 9.8 | Recalculate Fantasy Points | ✅ Aligned | `POST /recalculate` applies current weights to all stored stats, returns record count, logged in audit. |
| 9.9 | Manual League Ingestion | ✅ Aligned | Admin enters league ID, triggers ingestion, seeds cards, enriches players, idempotent, logged. |
| 9.10 | Schedule Refresh | ✅ Aligned | Refresh button busts cache, re-fetches from Google Sheets URL, logged in audit. |
| 10.1 | Explain Scoring | ✅ Aligned | Collapsible "How is scoring calculated?" section on My Team tab listing weighted stats formula. |
| 10.2 | Schedule Tab | ✅ Aligned | Chronological list of all series across divisions. Upcoming shows date/team/stream link. Past shows start time and series result. Team names link to team modal. Stale cache notice shown. |
| 11.1 | Server-side Validation | ⚠️ Diverged | All state-changing actions validated server-side. Admin endpoints use `require_admin`. However, `is_admin` is cached in session at login and not re-verified from DB on each request — if admin status is revoked, the session still grants access until re-login. |
| 11.2 | Audit Logs | ✅ Aligned | Tracks registrations, logins, token draws, code redemptions, admin grants, ingestion, weight changes, recalculations, schedule refreshes, code creation/deletion. Each entry has timestamp, actor, action, detail. Visible in admin tab, most recent first. |

## Key divergences

1. **5.5 Re-roll Modifiers not implemented** — No endpoint or UI exists for spending a token to re-roll a card's modifiers and quality; update implementation.
2. **4.3/9.7 Admin Set Series Date not implemented** — No mechanism to override a series' date/week assignment or persist it across re-ingestions; update implementation.
3. **4.2 Activate/deactivate not gated by week lock** — The `/roster/{card_id}/activate` and `/deactivate` endpoints do not check whether the current week is locked, so users could theoretically change their roster after lock; update implementation.
4. **5.1 Free Weekly Token grant not visible** — The weekly token grant logic when a week locks is not present in `main.py` and `weeks.py` is not provided; verify `weeks.py` implementation or update implementation.
5. **9.6 Start New Season has no UI** — Story requires admin ability to reset DB and start a new season; no endpoint or button exists; update implementation.
6. **9.4 Manage Season Lifecycle incomplete** — No explicit season initiate/close controls; season is implicitly managed via env vars and auto-generated weeks; clarify story or update implementation.
7. **11.1 Admin re-verification from DB** — `is_admin` is read from session (set at login) rather than re-queried from the database on each admin request, so revoking admin privileges doesn't take effect until the user's session expires; update implementation.
8. **9.5 System Status dashboard missing** — Only a schedule debug endpoint exists; no comprehensive system status view (ingest status, cache age, background thread health) is shown in the admin UI; update implementation.
9. **1.3 Missing email error not surfaced** — Story says user without email should see an error; implementation returns 200 silently for all cases to prevent username enumeration — these conflict; clarify story.
10. **5.2 Token Log lacks weekly grant summary** — Audit log is generic; weekly free token grants are not logged with "total number of users affected" as required by the story; update implementation.
