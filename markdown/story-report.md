<!-- Generated automatically by scripts/story_report.py — do not edit by hand -->
_Last updated: 2026-03-28 15:55 UTC_

# Story Coverage Report

| ID | Story | Status | Notes |
|----|-------|--------|-------|
| 1.1 | User Registration | ⚠️ Diverged | Registration works with unique email/username, but no initial Kana tokens are granted (AC says 5 tokens; see also 2.1 which says 8). No registration timestamp is recorded on the User model. |
| 1.2 | User Login | ⚠️ Diverged | Login uses username + password (not email + username as AC states). Error message is "Invalid username or password" not "Login failed – Invalid credentials." No session/token mechanism exists—user_id is stored in localStorage with no server-side session. No redirect to dashboard; frontend just switches tab. |
| 1.3 | User Logout | ⚠️ Diverged | Logout clears localStorage but there is no server-side session to invalidate. Logged-out users can still call authenticated API endpoints by passing any user_id (no auth middleware). |
| 1.4 | Admin-only Access | ⚠️ Diverged | Admin routes check `require_admin(user_id)` but user_id is passed in request body/query—no real auth token. Any client can forge an admin request by guessing an admin user_id. Admin tab is hidden in UI but endpoints are unprotected. |
| 2.1 | Grant Starter Tokens on Registration | 🔲 Not implemented | Story says 8 Kana tokens at registration. No token/Kana balance field exists on User model; `draw_limit` defaults to 7 which is a different concept. No Kana token system is implemented. |
| 2.3 | View Reserve and Collection | ⚠️ Diverged | Roster endpoint returns active/bench cards but there is no separate "Collection" tab in the UI. Cards do not display two stats or quality as described—only card_type (rarity) is shown. No dedicated Reserve view; bench serves as reserve. |
| 2.4 | View Weekly Rosters | ⚠️ Diverged | Week selector exists and upcoming week defaults, but active slots are not shown as empty by default—"No active cards" text is shown instead of 5 empty slot placeholders. Lock time is shown but described as "every Sunday 24:00" whereas implementation uses `start_time - 1` of the next week. |
| 2.5 | View Current and Season Points | ⚠️ Diverged | Weekly points are shown per roster view, but there is no separate season-wide total point display for the user. No two separate point pools (weekly vs season) visible in UI. No dropdown for past weeks' points—a select element exists but doesn't show per-week point history summary. |
| 3.1 | Generate Cards for League Players | ⚠️ Diverged | Admin can ingest league players and seed cards, but card distribution uses types "common/rare/epic/legendary" not "white/blue/purple/golden" as AC specifies. Deck ratio (1 golden, 2 purple, 4 blue, 8 white per player) cannot be verified from main.py alone—seed logic is in external `seed.py` not provided. |
| 3.2 | Remove Cards from Pool | 🔲 Not implemented | No endpoint or UI to remove a player from the card pool. No Kana token compensation for removed cards. |
| 3.3 | Assign Randomized Card Quality | ⚠️ Diverged | Card quality is determined by which pre-seeded card is drawn (random.choice from unclaimed pool), not by a probability roll at draw time. Quality names differ from story (common/rare/epic/legendary vs white/blue/purple/golden). |
| 3.4 | Assign Two Randomized Stats | 🔲 Not implemented | Card model has no stats fields. No per-card stats are generated, stored, or displayed. No quality multiplier on points. |
| 3.5 | View Seasonal Reserve Cards | ⚠️ Diverged | Bench cards are shown in roster view but there is no filtering/sorting capability. Card stats and per-card points are not displayed as specified. |
| 3.6 | View Permanent Collection | 🔲 Not implemented | No collection tab, no cross-season card tracking, no duplicate replacement logic. |
| 4.1 | Place Cards into Active Slots | ⚠️ Diverged | 5-slot limit enforced via `ROSTER_LIMIT`. Activate/deactivate endpoints exist. However, cards do not lock—no check against week lock state in activate/deactivate endpoints. |
| 4.2 | Lock Active Cards | ⚠️ Diverged | `auto_lock_weeks` runs at startup and weekly_roster_entries snapshot exists, but activate/deactivate endpoints do not check `is_locked` status—users can modify roster even for locked weeks. UI hides buttons but API is unprotected. |
| 4.3 | Resetting Cards | ⚠️ Diverged | Individual deactivate exists ("Bench" button), but no "reset all" button. No server-side lock check prevents reset on locked rosters. |
| 4.5 | Preserve Points | ⚠️ Diverged | Weekly roster snapshots exist and past weeks can be viewed, but there is no cumulative season points total visible to the user. Past week data is accessible via week selector. |
| 5.1 | Free Weekly Token | 🔲 Not implemented | No Kana token model, no weekly token grant mechanism, no history recording. |
| 5.3 | Spend Token to Draw Card | ⚠️ Diverged | Drawing uses a `draw_limit` counter, not a Kana token balance. No confirmation popup before draw. No duplicate handling rules. |
| 5.4 | Redeem Kana Code | 🔲 Not implemented | No code redemption endpoint or UI. |
| 5.5 | Generate Kana Codes (Admin) | 🔲 Not implemented | No admin code generation feature. |
| 5.6 | View Token Balance | 🔲 Not implemented | No Kana token balance displayed. Draw counter shown instead. No min/max enforcement (0–100). |
| 5.7 | Re-roll Stats | 🔲 Not implemented | No re-roll endpoint, no card stats to re-roll, no confirmation popup. |
| 6.1 | Score Active Cards | ⚠️ Diverged | Scoring uses player_match_stats fantasy_points scoped by week time range. Only active (snapshotted) cards score for locked weeks. However, no explicit double-counting prevention per the scoring query. |
| 6.2 | Configure Event Weights (Admin) | ⚠️ Diverged | Weight editing exists and recalculate endpoint reprocesses all stats—but it affects historical data too, not "only future scoring" as AC requires. No change logging. |
| 6.3 | Card Stat Scoring | 🔲 Not implemented | Cards have no stats. Scoring is based on player match data, not card-specific stat mappings with bonus points. |
| 6.4 | Track Season Points | ⚠️ Diverged | Roster leaderboard shows total roster value, but no dedicated per-user season point total visible in the user's own view. |
| 6.5 | Track Points per Card | ⚠️ Diverged | Weekly points per card shown in roster view, but no historical per-card-per-week breakdown is available. |
| 6.6 | Prevent Duplicate Scoring | ❓ Ambiguous | player_match_stats has a unique id and match_id FK, but there's no explicit unique constraint on (player_id, match_id). Story is vague on "safe retries." |
| 7.1 | Fetch Player Data | ⚠️ Diverged | `ingest_league` and `run_enrichment` exist (imported from external modules). Validation/logging/retry details not visible in provided code. |
| 7.2 | Import Match Data | ⚠️ Diverged | Match data imported via ingest pipeline. Details in external `ingest.py` not provided for full evaluation. |
| 7.3 | Handle API Failures | ❓ Ambiguous | Auto-ingest wraps in try/except and prints errors. No admin visibility of failures in UI. Retry logic unclear. |
| 8.1 | Season Leaderboard | ⚠️ Diverged | `/leaderboard/roster` ranks users by roster value, but this is current active card total—not a true season points leaderboard across all weeks. |
| 8.2 | Scrollable Leaderboard | ⚠️ Diverged | Leaderboard is on a tab but no explicit scrollable container for long lists. No CSS overflow handling visible. |
| 8.3 | Show User Rank | 🔲 Not implemented | User's own rank is not highlighted or always visible in the leaderboard. |
| 8.4 | Weekly Leaderboard | 🔲 Not implemented | No weekly leaderboard endpoint or UI. Only season-total roster leaderboard exists. |
| 9.1 | Generate Codes | 🔲 Not implemented | No Kana code system. |
| 9.2 | Grant Tokens | ⚠️ Diverged | `/grant-draws` grants extra draw limit, not Kana tokens. Conceptually similar but different system. |
| 9.3 | Configure Scoring | ⚠️ Diverged | Weight editing exists but affects all data (not just future). No audit logging. |
| 9.4 | Manage Season Lifecycle | 🔲 Not implemented | No season start/end/reset management endpoints or UI. |
| 9.5 | View System Status | ⚠️ Diverged | `/schedule/debug` exists for schedule diagnostics, but no general system status dashboard (ingestion status, user counts, etc.). |
| 9.6 | Start New Season | 🔲 Not implemented | No new season endpoint or workflow. |
| 10.1 | Explain Scoring | 🔲 Not implemented | No UI explanation of scoring rules, stat mappings, or quality multipliers. Weights table shown in admin only. |
| 11.1 | Server-side Validation | ⚠️ Diverged | Some validation exists (duplicate username/email, roster limits), but no real authentication—user_id is trusted from client. Any user can impersonate another by sending their user_id. |
| 11.2 | Audit Logs | 🔲 Not implemented | No audit log table or logging of registration rewards, token usage, draws, re-rolls, admin actions, or season resets. Only console prints exist. |

## Key divergences

1. **Kana token system entirely missing**: The codebase uses a `draw_limit` integer instead of a Kana token balance; no token granting, spending, weekly rewards, codes, or balance tracking exists. — *Update implementation.*

2. **Card stats not implemented**: Cards have no per-card stats (AC 3.4 requires exactly 2 stats per card with quality multipliers); scoring is based solely on player match data. — *Update implementation.*

3. **Story 1.1 vs 2.1 token conflict**: Story 1.1 says 5 starter tokens, Story 2.1 says 8 starter tokens; neither is implemented. — *Clarify story* (resolve the contradiction), then *update implementation.*

4. **No real authentication or session management**: User identity is stored in localStorage and passed as a plain user_id; there are no tokens, sessions, or middleware—any API caller can impersonate any user. — *Update implementation.*

5. **Permanent Collection not implemented**: No collection tab, no cross-season tracking, no duplicate-replacement logic (Stories 2.3, 3.6). — *Update implementation.*

6. **Roster lock not enforced server-side**: Activate/deactivate endpoints do not check whether the current week is locked; only the UI hides buttons. — *Update implementation.*

7. **Card quality naming mismatch**: Implementation uses "common/rare/epic/legendary" while stories specify "white/blue/purple/golden" with specific deck ratios (1/2/4/8 per player). — *Clarify story* (agree on naming) and *update implementation* (enforce ratios).

8. **No audit logging**: Stories require detailed audit trails for draws, re-rolls, admin actions, token usage, and season resets; only `print()` statements exist. — *Update implementation.*

9. **Weekly and season leaderboards missing**: Only an all-time roster value leaderboard exists; no weekly ranking, no user-rank highlight, and no season points leaderboard per the story requirements (8.1–8.4). — *Update implementation.*

10. **Weight recalculation affects historical data**: Story 6.2 requires changed weights to affect only future scoring, but `/recalculate` rewrites all historical fantasy_points. — *Update implementation.*
