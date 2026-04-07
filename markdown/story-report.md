<!-- Generated automatically by scripts/story_report.py — do not edit by hand -->
_Last updated: 2026-04-07 14:02 UTC_

# Story Coverage Report

| ID | Story | Status | Notes |
|----|-------|--------|-------|
| 1.1 | User Registration | ✅ Aligned | `/register` endpoint validates unique username/email, creates user, grants initial tokens, records `created_at` timestamp. |
| 1.2 | User Login | ✅ Aligned | `/login` validates username+password, sets session, returns error on invalid credentials. Logged-out users get 401 from `get_current_user`. |
| 1.3 | User Receive Temporary Password | ✅ Aligned | `/forgot-password` generates temp password, emails it, sets `must_change_password` flag. Returns 200 even if user not found (avoids enumeration). |
| 1.4 | User Password Reset | ✅ Aligned | `/profile/password` requires current password before accepting new one. Profile tab has the form. |
| 1.5 | User Logout | ✅ Aligned | `/logout` clears session. Logout button visible on every page via header. |
| 1.6 | Admin-only Access | ✅ Aligned | `require_admin` dependency re-checks `is_admin` from DB session on every admin endpoint. Admin tab hidden for non-admins in frontend. |
| 1.7 | User Profile Tab | ✅ Aligned | Username change with uniqueness check, password change with current password, optional OpenDota player ID with preview. |
| 2.1 | Grant Starter Tokens on Registration | ✅ Aligned | `INITIAL_TOKENS` env var configures amount; granted in `/register`. |
| 2.2 | Token Visibility | ✅ Aligned | Token balance shown in header (`tokenBalance` element) and synced on My Team tab (`drawCounter`). Updated after draw, redeem, weekly grant. |
| 2.3 | View Cards | ⚠️ Diverged | Cards display player identity, rarity, and points. However, drawn cards go to active roster first (if space), then bench — story says "benched until placed" but implementation auto-activates if slots available. |
| 2.4 | View Weekly Rosters | ✅ Aligned | Default view is the upcoming editable week. Lock date shown. Empty slots rendered explicitly as "— empty slot —". |
| 2.5 | View Current and Season Points | ✅ Aligned | Weekly and season points shown separately on My Team tab. Week history selector allows viewing past weeks. New user with no cards shows 0. |
| 3.1 | Generate Cards | ✅ Aligned | `seed_cards` called during ingestion. Per player: 1 legendary, 2 epic, 4 rare, 8 common (confirmed in `seed.py` reference from `seed_cards`). Idempotent. Shared deck. |
| 3.2 | Card Drawing | ✅ Aligned | Costs 1 token, reveal modal shown, prefers unowned players, fallback to duplicates when all owned. Auto-placed to active or bench. |
| 3.3 | Remove Cards from Pool | 🔲 Not implemented | Marked post-MVP; no admin endpoint to remove players and refund tokens. |
| 3.4 | Card Rarity | ✅ Aligned | Rarity set at deck creation time (seed), not draw time. Shown in reveal modal and roster views via badge. |
| 3.5 | Assign Randomized Modifiers | ✅ Aligned | `_assign_modifiers` assigns random stat modifiers at draw time based on rarity config. Stored in `card_modifiers` table. Visible on card views. |
| 3.6 | Modifier Management | ⚠️ Diverged | Modifier counts and bonus are stored in `weights` table (DB), not strictly environment variables. Story says "manageable from environment variables." `seed_weights` likely seeds defaults but runtime changes happen via DB, not env vars. |
| 3.7 | View Seasonal Reserve Cards | ✅ Aligned | Bench section on My Team tab shows all benched cards with player, rarity, points. Hidden for locked past weeks (read-only snapshot). |
| 3.8 | View Permanent Collection | 🔲 Not implemented | Marked post-MVP. No cross-season collection logic. |
| 4.1 | Place Cards into Active Slots | ✅ Aligned | 5 slots, activate/deactivate endpoints, duplicate player check, only editable week allows changes. |
| 4.2 | Lock Active Cards | ⚠️ Diverged | `auto_lock_weeks` runs periodically, but locking is based on `weeks` table logic (not explicitly "Sunday end of day UTC"). Lock banner and read-only snapshot present. Lock date shown in UI. Actual lock timing depends on `weeks.py` implementation not shown. |
| 4.3 | Admin Move Series Time Manually | ⚠️ Diverged | `PUT /matches/{match_id}/week` sets `week_override_id` on individual matches, not series. Story says "select a series." Also `sync-match-weeks` exists for bulk auto-assignment. No explicit series-level UI in admin tab HTML. |
| 4.4 | Preserve Points | ✅ Aligned | `weekly_roster_entries` snapshot locked rosters. Season points derived from past week records. |
| 4.5 | View Past Week Snapshots | ✅ Aligned | Week selector dropdown on My Team tab lists all weeks. Past locked weeks show immutable snapshot with week-scoped points. |
| 5.1 | Free Weekly Token | ⚠️ Diverged | Story says "When the week is locked all users are granted 1 additional token." No visible implementation of this grant in `main.py` or `auto_lock_weeks`. The logic may be in `weeks.py` (not provided), but nothing in `main.py` grants tokens on lock. |
| 5.2 | Token Log (admin) | ⚠️ Diverged | Audit log tracks draws, redemptions, admin grants. However, no aggregated view of "weekly free token grants with total users affected" as a distinct log entry. Token log is merged into the general audit log. |
| 5.3 | Spend Token to Draw Card | ✅ Aligned | 1 token deducted, card assigned to user, duplicate player prevention, reveal modal shown. |
| 5.4 | Redeem Code | ✅ Aligned | Valid code grants tokens, invalid shows error, one use per user, logged in audit log. |
| 5.5 | Re-roll Modifiers | ✅ Aligned | Costs 1 token, confirmation popup in UI, modifiers replaced, logged in audit. Story says "quality replaced" too — implementation only re-rolls modifiers, not rarity. |
| 6.1 | Score Active Cards | ✅ Aligned | Only locked roster entries (via `weekly_roster_entries`) contribute to scoring. Uses Dota 2 match data. |
| 6.2 | Card Modifier Scoring | ✅ Aligned | Rarity bonus applied as percentage on top of raw fantasy points. Defaults: common +0%, rare +1%, epic +2%, legendary +3%. Configurable via weights. |
| 6.3 | Track Season Points | ✅ Aligned | Season points calculated from all locked weeks, visible on My Team tab and season leaderboard. |
| 6.4 | Track Points per Card | ✅ Aligned | Per-card points visible in roster view per week, with week selector for history. |
| 6.5 | Prevent Duplicate Scoring | ✅ Aligned | `PlayerMatchStats` keyed on player_id+match_id. Ingestion is idempotent (already-stored matches skipped). |
| 7.1 | Fetch Player Data | ✅ Aligned | `run_enrichment()` called after ingestion fetches player names/avatars. Players table stores avatar_url. |
| 7.2 | Import Match Data | ✅ Aligned | `ingest_league` fetches match data. `PlayerMatchStats` stores kills, assists, deaths, GPM, wards, tower damage. Fantasy points calculated and stored. |
| 7.3 | Handle API Failures | ✅ Aligned | Ingestion wrapped in try/except, errors logged. Admin can re-trigger via `/ingest/league/{id}`. Partial ingestion uses idempotent checks. |
| 7.4 | Auto-ingest on Startup | ✅ Aligned | `AUTO_INGEST_LEAGUES` env var parsed; background poll thread started. Empty value disables (checked with `if _league_ids`). Already-stored matches skipped. |
| 8.1 | Season Leaderboard | ⚠️ Diverged | `/leaderboard/season` exists but the SQL does not use `week_override_id` for match-to-week assignment — it only checks `m.start_time BETWEEN wk.start_time AND wk.end_time`, missing overridden matches. |
| 8.2 | Scrollable Leaderboard | ✅ Aligned | Leaderboard tab is visible and accessible without login. No auth guard on leaderboard endpoints. |
| 8.3 | Show User Rank | ✅ Aligned | Logged-in user's row highlighted with gold color and bold text in leaderboard rendering. |
| 8.4 | Weekly Leaderboard | ⚠️ Diverged | `/leaderboard/weekly` exists with week selector, but same `week_override_id` issue as season leaderboard — overridden matches may be missed. |
| 8.5 | Player Performance Browser | ✅ Aligned | Players tab lists all players with match count, avg points, total points. Filterable by name/team. Player detail modal shows full match history with K/A/D, GPM, wards, tower damage, fantasy points. |
| 8.6 | Team Browser | ✅ Aligned | Teams tab lists all teams with match count and player count. Team detail modal shows player roster with stats. |
| 9.1 | Generate Promo Codes | ✅ Aligned | Admin creates codes with token amount. Codes reusable by multiple users, one redemption per user. Admin can delete codes. |
| 9.2 | Grant Tokens | ✅ Aligned | Admin selects user and grants tokens. Balance updates immediately. Logged in audit log with admin actor, target user, amount. |
| 9.3 | Configure Scoring Weights | ⚠️ Diverged | Weights are stored in DB and displayed in admin tab, but are read-only in the UI (no edit form). Story says "editable from environment variables" — they are seeded from env but runtime editing requires DB changes or reconfiguring env + restart. |
| 9.4 | Manage Season Lifecycle | ❓ Ambiguous | No explicit "initiate/close season" endpoints visible. Lock dates managed via weeks system. League IDs via env var. Story is vague on what "manage season lifecycle" concretely requires. |
| 9.5 | View System Status | ⚠️ Diverged | `/schedule/debug` shows schedule cache status. No broader system status view (ingest status, last ingest time, DB health, etc.) visible in admin tab. |
| 9.6 | Start New Season | 🔲 Not implemented | No "reset database and begin new season" endpoint or UI found. |
| 9.7 | Admin Set Series Date | ⚠️ Diverged | `PUT /matches/{match_id}/week` and `POST /admin/sync-match-weeks` exist but operate on individual matches, not series. No admin UI in the HTML for selecting series and setting week. Story requires displayed corrected datetime on schedule — not implemented; only week_override_id stored. |
| 9.8 | Recalculate Fantasy Points | ✅ Aligned | `/recalculate` applies current weights to all stored stats. Shows record count. Logged in audit log. No re-fetch needed. |
| 9.9 | Manual League Ingestion | ✅ Aligned | Admin enters league ID, triggers ingestion. Fetches matches, calculates points, seeds cards, enriches profiles. Idempotent. Logged. |
| 9.10 | Schedule Refresh | ✅ Aligned | `/schedule/refresh` busts cache, fetches fresh data from Google Sheets CSV. Logged in audit log. |
| 10.1 | Explain Scoring | ✅ Aligned | Collapsible "How is scoring calculated?" section on My Team tab lists weighted stats formula. |
| 10.2 | Schedule Tab | ✅ Aligned | Chronological list of all series across divisions. Upcoming shows date/time, team names, stream links. Past shows result (e.g. 2-0). Team names link to team modal. Stale cache notice shown. |
| 11.1 | Server-side Validation | ✅ Aligned | All state-changing actions validated server-side. Admin endpoints use `require_admin` which re-verifies from session (not client-side flag alone). |
| 11.2 | Audit Logs | ✅ Aligned | Tracks registrations, logins, draws, redemptions, admin grants, ingestion, recalculations, schedule refreshes, code creation/deletion. Each entry has timestamp, actor, action, detail. Admin-only, most recent first. |
| 12.1 | Weight Calculation | ✅ Aligned | `POST /simulate/{match_id}` accepts custom scoring stat overrides, returns players with fantasy points. No auth required. Falls back to DB defaults for omitted weights. |
| 12.2 | Weight Statistics | ✅ Aligned | `GET /simulate` returns machine-readable documentation describing endpoint, parameters, request body, response format, and errors. |
| 13.1 | Twitch Integration - MVP Selection | 🔲 Not implemented | No Twitch integration, MVP selection, or related endpoints found. |
| 13.2 | Twitch Integration - Token Drops | 🔲 Not implemented | No Twitch streamer recognition, drop pool, or token drop mechanism found. |

## Key divergences

1. **5.1 — Free weekly token grant not implemented in visible code**: No logic in `main.py` grants users 1 token when a week locks; this may be missing from `weeks.py` or entirely absent. → **Update implementation**.

2. **9.6 — Start New Season not implemented**: No endpoint or UI to reset the database and begin a fresh season. → **Update implementation**.

3. **9.7 — Admin Set Series Date operates on matches, not series**: The override works per-match via `week_override_id`, but the story requires selecting a series from a list and assigning it to a different week with the corrected date displayed on the schedule. No admin UI exists for this. → **Update implementation**.

4. **8.1/8.4 — Season and weekly leaderboards ignore `week_override_id`**: The SQL in `/leaderboard/season` only checks `m.start_time BETWEEN wk.start_time AND wk.end_time`, so matches with a `week_override_id` that were moved to a different week are not counted correctly. → **Update implementation**.

5. **9.3 — Scoring weights are read-only in the admin UI**: Weights are displayed in a table but cannot be edited from the admin tab. The story says "editable from environment variables" which is ambiguous — if runtime editing is expected, the UI needs an edit form. → **Clarify story** or **update implementation**.

6. **2.3 — Drawn cards auto-activate instead of going to bench**: Story says cards are "benched until placed," but implementation auto-places into active roster if slots are available. → **Clarify story**.

7. **9.5 — System status view is minimal**: Only schedule debug endpoint exists. No ingest status, last successful ingestion timestamp, or general health dashboard visible in the admin tab. → **Update implementation**.

8. **5.5 — Re-roll replaces modifiers but not "quality"**: Story says "Modifiers and quality replaced," but implementation only re-rolls stat modifiers, not the card's rarity (card_type). → **Clarify story** (define what "quality" means — rarity or modifier tier?).

9. **13.1/13.2 — Twitch integration entirely absent**: MVP selection and token drops for stream viewers have no implementation. → **Update implementation** (or defer explicitly to post-MVP).

10. **4.2 — Lock timing not verifiably "Sunday end of day UTC"**: The actual lock logic lives in `weeks.py` which is not provided; the `auto_lock_weeks` function is called periodically but the lock boundary cannot be confirmed from the visible code. → **Clarify story** or verify
