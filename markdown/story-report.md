<!-- Generated automatically by scripts/story_report.py — do not edit by hand -->
_Last updated: 2026-03-29 18:26 UTC_

# Story Coverage Report

| ID | Story | Status | Notes |
|----|-------|--------|-------|
| 1.1 | User Registration | ⚠️ Diverged | Registration works with unique email/username. However, no initial Kana tokens are granted on registration (AC says 5 tokens). No timestamp of registration is recorded in the User model. |
| 1.2 | User Login | ⚠️ Diverged | Login uses username + password, not email + username as AC specifies. Error message is "Invalid username or password" not "Login failed – Invalid credentials." No session/token mechanism; user_id stored in localStorage only. No redirect to dashboard; frontend stays on current tab. |
| 1.3 | User Logout | ⚠️ Diverged | Logout clears localStorage but there is no server-side session to invalidate. Logged-out users can still call API endpoints directly (no auth middleware). Redirect to login screen not explicitly implemented (switches to leaderboard tab). |
| 1.4 | Admin-only Access | ⚠️ Diverged | Admin routes check `require_admin` server-side. Admin tab hidden in UI for non-admins. However, admin auth is based on `is_admin` flag, not tied to specific login credentials. Some admin endpoints (e.g., PUT `/weights/{key}`) lack admin checks entirely. |
| 2.1 | Grant Starter Tokens on Registration | 🔲 Not implemented | Story says 8 Kana tokens at registration. No token/Kana balance system exists in the codebase. The `draw_limit` field defaults to 7, which is a different concept (draw cap, not tokens). |
| 2.3 | View Reserve and Collection | ⚠️ Diverged | Roster view shows active and bench cards with player name, rarity, and points. However: no two stats displayed per card, no quality shown on card detail, no separate Collection tab exists, no separate Reserve view. Bench ≈ reserve but no dedicated UI. |
| 2.4 | View Weekly Rosters | ⚠️ Diverged | Week selector exists and upcoming week is default. Slots are not visually empty by default (just shows "No active cards"). Lock timing is shown but described as a date, not explicitly "every Sunday 24:00". |
| 2.5 | View Current and Season Points | ⚠️ Diverged | Weekly points shown per roster. No separate season-total points displayed for the user. No two separate point pools (weekly vs season) visible in UI. No dropdown for past weeks' points (uses week selector instead). New user 0-point state not explicitly handled. |
| 3.1 | Generate Cards for League Players | ⚠️ Diverged | Admin can ingest leagues and `seed_cards` generates cards. Card types are "common/rare/epic/legendary" not "white/blue/purple/golden" as in story. Deck distribution logic is in `seed.py` (not shown) so exact 1/2/4/8 ratio unverifiable. No explicit "reload deck before season start" or duplicate-avoidance in permanent pool visible. |
| 3.2 | Remove Cards from Pool | 🔲 Not implemented | No endpoint or UI to remove a player from the card pool. No Kana token refund mechanism exists. |
| 3.3 | Assign Randomized Card Quality | ⚠️ Diverged | Cards have a `card_type` (quality), drawn randomly from the pool. Quality names differ from story (common/rare/epic/legendary vs white/blue/purple/golden). Probability is based on pool composition, which may match distribution. Quality is stored but not prominently visible in card detail UI. |
| 3.4 | Assign Two Randomized Stats | 🔲 Not implemented | Card model has no stat fields. No two-stat system exists. No stat-based point generation or quality multiplier. |
| 3.5 | View Seasonal Reserve Cards | ⚠️ Diverged | Bench cards shown in roster view with player/rarity/points. No card stats displayed (stats not implemented). No filtering or sorting available on reserve cards. |
| 3.6 | View Permanent Collection | 🔲 Not implemented | No collection tab or view exists. No cross-season card tracking. No quality-replacement logic. |
| 4.1 | Place Cards into Active Slots | ⚠️ Diverged | 5-slot roster limit enforced. Activate/deactivate endpoints exist. However, no lock check on activate/deactivate—cards can be changed even for locked weeks. Slots are not individually defined (just a count). |
| 4.2 | Lock Active Cards | ⚠️ Diverged | Weeks auto-lock via `auto_lock_weeks`. UI shows lock state and hides bench/deactivate buttons for locked weeks. However, backend activate/deactivate endpoints don't enforce lock state—cards can still be changed via API. |
| 4.3 | Resetting Cards | ⚠️ Diverged | Deactivate (bench) individual cards exists. No "reset all" button. No lock enforcement on the backend for reset operations. |
| 4.5 | Preserve Points | ⚠️ Diverged | Weekly roster snapshots exist via `WeeklyRosterEntry`. Past weeks return snapshot data. However, past week points are recalculated from live match data (not frozen), so they could change if data is re-ingested. No cumulative season point tracking. |
| 5.1 | Free Weekly Token | 🔲 Not implemented | No Kana token system exists. No weekly token grant mechanism. No token history. |
| 5.3 | Spend Token to Draw Card | 🔲 Not implemented | Drawing uses a `draw_limit` counter, not a token spend. No confirmation popup before draw. No token deduction. Duplicate rules not implemented. |
| 5.4 | Redeem Kana Code | 🔲 Not implemented | No code redemption endpoint or UI. |
| 5.5 | Generate Kana Codes (Admin) | 🔲 Not implemented | No admin code generation feature. |
| 5.6 | View Token Balance | 🔲 Not implemented | No token balance displayed. Draw counter shown instead (`draws_used / draw_limit`). No min/max enforcement (0–100). |
| 5.7 | Re-roll Stats | 🔲 Not implemented | No re-roll mechanism. No card stats to re-roll. No token cost system. |
| 6.1 | Score Active Cards | ⚠️ Diverged | Fantasy points computed from Dota 2 match data via `player_match_stats`. Only active card points displayed. However, scoring is on player level not card level; no card-specific scoring. Duplicate match scoring prevention not explicitly visible. |
| 6.2 | Configure Event Weights (Admin) | ⚠️ Diverged | Weights editable in admin UI. Recalculate applies to all stats (not just future). PUT `/weights/{key}` has no admin check. No logging of weight changes. |
| 6.3 | Card Stat Scoring | 🔲 Not implemented | Cards have no stats. Scoring is player-match-level, not card-stat-level. No bonus points from card stats. |
| 6.4 | Track Season Points | ⚠️ Diverged | Combined weekly points shown in roster. No persistent season-total accumulation. No dedicated season points display. |
| 6.5 | Track Points per Card | ⚠️ Diverged | Per-week points shown per card in roster view. No historical per-card breakdown across weeks. |
| 6.6 | Prevent Duplicate Scoring | ❓ Ambiguous | `player_match_stats` has unique rows per player/match but no explicit unique constraint visible in model. Ingest deduplication logic is in `ingest.py` (not provided). |
| 7.1 | Fetch Player Data | ❓ Ambiguous | `ingest.py` and `enrich.py` referenced but not provided. Player data exists in DB. Cannot fully verify validation/logging/retry. |
| 7.2 | Import Match Data | ❓ Ambiguous | Match import referenced via `ingest_league`. Implementation not provided. |
| 7.3 | Handle API Failures | ❓ Ambiguous | Auto-ingest has try/except with print logging. Full retry/failure handling in `ingest.py` not visible. |
| 8.1 | Season Leaderboard | ⚠️ Diverged | Roster leaderboard exists ranked by roster_value (sum of active card player points). This is all-time, not strictly season-scoped. Leaderboard is for users, which aligns. |
| 8.2 | Scrollable Leaderboard | ⚠️ Diverged | Leaderboard is on a separate tab. Not explicitly scrollable (standard HTML table, browser scroll). |
| 8.3 | Show User Rank | 🔲 Not implemented | Current user's rank is not highlighted or persistently visible on the leaderboard or elsewhere. |
| 8.4 | Weekly Leaderboard | 🔲 Not implemented | No weekly leaderboard. Roster leaderboard is all-time only. |
| 9.1 | Generate Codes | 🔲 Not implemented | No Kana code generation. |
| 9.2 | Grant Tokens | ⚠️ Diverged | Admin can grant extra draws (draw_limit), not Kana tokens. Different mechanism than specified. |
| 9.3 | Configure Scoring | ✅ Aligned | Admin can edit scoring weights and recalculate. |
| 9.4 | Manage Season Lifecycle | 🔲 Not implemented | No season start/end/reset controls in admin UI or backend. |
| 9.5 | View System Status | 🔲 Not implemented | No system status dashboard. Schedule debug endpoint exists but not a general status view. |
| 9.6 | Start New Season | 🔲 Not implemented | No new season endpoint or UI. |
| 10.1 | Explain Scoring | 🔲 Not implemented | Scoring weights visible in admin panel only. No user-facing explanation of how stats map to points. |
| 11.1 | Server-side Validation | ⚠️ Diverged | Some validation exists (duplicate username/email, draw limits). However, no auth tokens/sessions—user_id passed in request body is trusted without verification. Activate/deactivate not lock-checked server-side. Weight updates lack admin check. |
| 11.2 | Audit Logs | 🔲 Not implemented | No audit log table or logging mechanism. Console prints exist for ingest but no structured audit trail for registration, token usage, draws, re-rolls, admin actions, or season resets. |

## Key divergences

1. **No Kana token system exists** — The entire token economy (balance, spending, weekly grants, codes) is absent; the codebase uses a simple `draw_limit` counter instead. **Update implementation.**

2. **Cards have no stats** — Stories 3.4, 5.7, and 6.3 require two randomized stats per card with quality multipliers; the Card model only has `card_type` and no stat fields. **Update implementation.**

3. **No permanent Collection view** — Story 3.6 requires a cross-season collection tab with deduplication and quality replacement; nothing exists. **Update implementation.**

4. **Registration grants no starter tokens** — Stories 1.1 (5 tokens) and 2.1 (8 tokens) both require tokens on signup; neither is implemented, and the two stories contradict each other on the amount (5 vs 8). **Clarify story** (resolve the 5 vs 8 conflict), then **update implementation.**

5. **No server-side authentication/session management** — Login returns a user object stored in localStorage; any API call can impersonate any user by passing a different `user_id`. Logout doesn't invalidate anything server-side. **Update implementation.**

6. **Active roster lock not enforced on backend** — Activate/deactivate endpoints don't check whether the current week is locked, allowing roster changes for locked weeks via direct API calls. **Update implementation.**

7. **Card quality naming mismatch** — Implementation uses common/rare/epic/legendary; stories specify white/blue/purple/golden. **Clarify story** or **update implementation** to align naming.

8. **No audit logging** — Story 11.2 requires structured audit logs for all key actions with timestamps and actors; only console prints exist. **Update implementation.**

9. **No weekly or season-scoped user leaderboard** — Stories 8.3 and 8.4 require the user's own rank to be always visible and a weekly leaderboard; neither exists. **Update implementation.**

10. **Weight update endpoint lacks admin authorization** — `PUT /weights/{key}` has no `require_admin` check, allowing any user to modify scoring weights. **Update implementation.**
