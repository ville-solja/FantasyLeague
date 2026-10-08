# Feature Documentation

Feature docs are split into two tiers: **Core** features that are user-facing and frequently referenced, and **Reference** features covering implementation details, integrations, and tooling.

---

## Core Features

These describe the primary user-visible surfaces of the app.

| Feature | Description |
|---|---|
| [Authentication & Accounts](core/auth.md) | Registration, login, sessions, profile management, forgot-password |
| [Cards & Rarities](core/cards.md) | Card generation, rarity distribution, modifiers, scoring formula, reroll |
| [Weeks & Leaderboards](core/weeks.md) | Weekly roster locks, scoring windows, and leaderboard types |
| [Weekly Summary Report](core/weekly-summary.md) | Post-week recap popup: series-grouped matches, VOD links, and a per-user Reveal-results gate for MVP highlights and points earned |
| [Weekly Report Fixes](core/weekly-report-fixes.md) | Docked reveal-all control, spoiler-safe winner hiding before reveal, match date display, and (#151) a side-by-side roster panel with per-game card points, a themed scrollbar and a once-per-week new-recap popup for the Weekly Summary Report |
| [Players & Teams](core/players.md) | Player and team browse endpoints with match history |
| [Admin Features](core/admin.md) | Promo codes, token grants, weights, ingest, schedule, audit log |
| [Twitch Extension](core/twitch-extension.md) | Viewer panel game (Live, Join with the Twitch login, cards, roster), broadcaster MVP selection and token drops |

---

## Reference Features

Implementation details, integrations, and operator tooling.

| Feature | Description |
|---|---|
| [Terminology](reference/terminology.md) | Definitions for all domain concepts (League, Card, Deck, Roster, Week, etc.) |
| [Data Ingest](reference/ingest.md) | How match data flows from OpenDota into the app |
| [OpenDota Query Prioritization](reference/opendota-query-prioritization.md) | Live-match-aware gating: skips low-priority enrichment and tightens the poll interval while a monitored league has a match in progress |
| [Card Image Generation](reference/card-image-generation.md) | Pillow-based PNG card rendering pipeline |
| [Card Team Logo Placeholder](reference/card-team-logo-placeholder.md) | Solid black circular placeholder for a card's team-logo slot when no logo can be resolved yet |
| [Toornament Integration](reference/toornament.md) | Automatic result sync to toornament.com |
| [Player Profile Enrichment](reference/player-profile-enrichment.md) | AI-generated player bios from OpenDota stats |
| [Point Simulator](reference/point-simulator.md) | The `/simulate` endpoint for testing scoring weights |
| [Automated Testing](reference/automated-testing.md) | Playwright UI suite and GitHub Actions CI setup |
| [Version Visibility](reference/version-visibility.md) | Faint build version badge on every page |
| [Configuration & Commands](reference/commands.md) | Environment variables and useful admin commands |
| [My Team Tab Layout](reference/my-team-tab-layout.md) | Two-column desktop layout for the My Team tab |
| [Card Player Popup Navigation](reference/card-player-popup.md) | Clickable player name on viewed card; modal stacking fix |
| [Tester Account Exclusion](reference/tester-account-exclusion.md) | `is_tester` flag; admin toggle; leaderboard filtering |
| [Profile Header Link](reference/profile-header-link.md) | Clickable username button in header; one-click access to Profile tab |
| [MVP Fantasy Bonus](reference/mvp-fantasy-bonus.md) | Per-match score bonus for the Twitch-appointed MVP; configurable weight |
| [How to Play Tab](reference/how-to-play-tab.md) | In-app rules tab organised into role-based subtabs (Users/Players/Streamers/Developers): getting started, Twitch MVP flow, live scoring formula display |
| [Guided Tour](reference/guided-tour.md) | Spotlight tour of My Team (draw, chances, roster, weekly lock, points, Weekly Report, leaderboards), started from How to Play; automatic first-visit start off by default (`GUIDED_TOUR_AUTOSTART`) |
| [Twitch MVP Series Window](reference/twitch-mvp-series-window.md) | Cross-week series list for MVP panel; live ingest polling interval |
| [Early MVP Selection](reference/early-mvp-selection.md) | Lists matches in the MVP panel from Steam's live league list (since #161) before stats are ingested; bonus applied at ingest; faster polling right after a game |
| [MVP Selection Delays](reference/mvp-selection-delays.md) | Live games come from Steam's live league list (OpenDota `/live` dropped), checked in their own thread every minute; per-match timings for admins and a freshness line in the MVP picker |
| [Twitch Panel Abuse Limits](reference/twitch-panel-abuse-limits.md) | Soft accounts join drop pools after a minimum age, pool-size spikes are flagged, logged-out heartbeats are ignored, team logos load only from allowed hosts, and CORS allows only our extension's origin (#171) |
| [Approved Streamers Admin](reference/approved-streamers-admin.md) | Admins approve the Twitch channels allowed to set match MVPs from requests recorded when a broadcaster opens the MVP tool; `TWITCH_MVP_CHANNEL_IDS` still works alongside (#175) |
| [Twitch Integration Status](reference/twitch-integration-status.md) | Panel reason codes, a connection check on the extension configuration page, an admin Twitch status checklist, and a version and origins stamp in each package |
| [Twitch Chat Announcement Fix](reference/twitch-chat-announcement-fix.md) | Adds the required `extension_id`/`extension_version` fields to MVP chat announcements, fits them to 280 characters, and logs Twitch errors |
| [Twitch Extension Review Submission](reference/twitch-extension-review-submission.md) | EBS URL/endpoint disclosure, legal page links, and guideline-compliance notes for submitting the Extension to Twitch review |
| [Twitch Review Resubmission](reference/twitch-review-resubmission.md) | Fixes for the 2026-09 review rejection: extension 404 (console asset paths, Hosted Test), EBS fetch allowlist, and chat-capability disclosure |
| [Token Grant Event](reference/token-grant-event.md) | Admin-configured time-bounded token distribution; auto-claimed on next login |
| [Notification System](reference/notification-system.md) | Admin-configured time-bounded broadcast messages; one-time popup per player |
| [Admin Week Management](reference/admin-week-management.md) | Admin CRUD for week records: custom lock times, create/delete unlocked weeks, inline table editing, overlap prevention |
| [Week Boundary Formula Fix](reference/week-boundary-formula-fix.md) | Applies the grace-period offset to both week-boundary ends so a normal Monday-start/Sunday-end week never overlaps the next by default |
| [DB Sustainability](reference/db-sustainability.md) | Versioned schema migration registry; pre-deploy backup script |
| [Admin DB Backup](reference/admin-db-backup.md) | Admin-panel database backups: create on demand with a cooldown, list existing backups, and download a copy off the server |
| [Table Element Sortability](reference/table-element-sortability.md) | Client-side sortable column headers for the Players tab table |
| [Card Draw Modal UX](reference/card-draw-modal-ux.md) | Enter-key support, dynamic button label, and backdrop-click dismiss for the draw modal |
| [Prevent Common Card Reroll](reference/prevent-common-card-reroll.md) | Backend 400 guard and hidden Reroll button for common-rarity cards |
| [Env-Based Admin Seeding](reference/env-based-admin-seeding.md) | Replace hardcoded seed credentials with `SEED_ADMIN_*` env vars (numbered suffixes seed further admins); empty `users.json` stub in repo; in-app promotion via `POST /users/{user_id}/toggle-admin` |
| [Process Diagrams](../process-diagrams.md) | Mermaid flowcharts: season lifecycle, token/card economy, admin tools overview |
| [Mermaid Process Documentation](reference/mermaid-process-docs.md) | What each diagram in `process-diagrams.md` covers and when to update it |
| [Agent Lessons Log](reference/agent-lessons-log.md) | Append-only lessons file read by agents at run start to avoid recurring pitfalls |
| [Technical Writer](reference/technical-writer.md) | `/technical-writer` agent: names a document's audience and core message, then proposes a concise rewrite for approval without losing facts |
| [Admin Router Organization](reference/admin-router-organization.md) | Module map for `backend/routers/admin_*.py` after splitting the single `admin.py` file by concern |
| [User Tag System](reference/user-tag-system.md) | Generic admin-granted tags shown as card stickers and leaderboard chips; new tags need only a DB row + image asset |
| [Player Linking and Tag Visibility](reference/player-linking-and-tag-visibility.md) | Profile tab shows user's own tags and hints to link Dota ID when tags exist but no player is linked |
| [Dynamic Card Creation](reference/dynamic-card-creation.md) | Cards generated at draw time with weighted rarity rolls and player proportionality bias; no shared pool |
| [Team Booster Draws](reference/team-booster-draws.md) | Team draw (internal name "booster"): one card for 3 Tokens, restricted to a chosen team's player roster; configurable cost |
| [Team Draw Explanation](reference/team-draw-explanation.md) | User-facing "team draw" naming for the booster draw, its How to Play explanation, and the admin cost label |
| [Gmail SMTP Integration](reference/gmail-smtp-integration.md) | Operator guide for using Gmail or Google Workspace as the SMTP relay; adds SSL mode (port 465) alongside existing STARTTLS |
| [Security Headers](reference/security-headers.md) | Starlette middleware that adds X-Content-Type-Options, Referrer-Policy, CSP frame-ancestors, and conditional HSTS to every response |
| [Security Review Fixes](reference/security-review-fixes.md) | Triage and fixes for the 2026-09-26 external review (issue #135): Twitch MVP eligibility and channel allowlist, escaping, reset-email failures, route limits, SRI and file hardening |
| [Security Audit 3](reference/security-audit-3.md) | Issue #136: Origin check against cross-site state changes, username allowlist, CORS limited to the Twitch extension, production guards on dev shortcuts, pip-audit in CI |
| [Twitch, Steam and Account Hardening](reference/twitch-steam-account-hardening.md) | Issue #163: extension backend pinned at packaging, fail-closed Twitch defaults, safe MVP chat names, reauth for admin token actions, reset and lockout abuse fixes, operator checklist (#169 and #171 shipped with PR 174) |
| [Username XSS Fix](reference/username-xss-fix.md) | Fixes a stored-XSS privilege-escalation vulnerability where an unescaped username could execute script (e.g. calling `toggleAdmin`) in an admin's session |
| [DB Volume Persistence](reference/db-volume-persistence.md) | Bind-mount persistence strategy for SQLite; explains why bind mount over named volume, `--volumes` safety, and reset procedure |
| [Admin Player Pool](reference/admin-player-pool.md) | Admin CRUD for the known player pool; soft-delete with automatic token refunds to card holders |
| [Admin Player Add Progress](reference/admin-player-add-progress.md) | Streamed per-ID progress for bulk player add; pending-state indicator for single add |
| [Draw Panel Redesign](reference/draw-panel-redesign.md) | Renames "Deck" to "Draw" and replaces card counts with normalised drop percentages from live weights |
| [Monitored Leagues Admin](reference/monitored-leagues-admin.md) | Runtime add/remove of monitored leagues; purge path for rolling back wrong ingests |
| [SMTP Password Recovery](reference/smtp-password-recovery.md) | Forgot-password flow: temporary password delivery via SMTP with stdout fallback for local dev |
| [Schedule Series Game Breakdown](reference/schedule-series-game-breakdown.md) | Expands each resolved series into per-game rows showing duration, team kills, and hero icons; results also derive directly from ingested matches when the schedule sheet has no row for them |
| [MVP Schedule Cache Bust](reference/mvp-schedule-cache-bust.md) | Admin and Twitch MVP-setting endpoints bust the schedule cache so a new MVP shows on the Schedule tab immediately instead of after up to an hour |
| [Schedule Fixtures API Source](reference/schedule-fixtures-api.md) | Structured JSON fixtures feed (`SCHEDULE_FIXTURES_URL`) as a preferred alternative to the Google Sheet CSV; same parsed shape downstream, "Time TBD" for unscheduled fixtures |
| [Schedule Visuals](reference/schedule-visuals.md) | Schedule tab redesign: Right now strip (live, next up, latest result), fantasy-week strip with a Now line, and spoiler-free hide/reveal of results linked to Weekly Report reveals |
| [Temporary Password Expiry](reference/temp-password-expiry.md) | Configurable TTL on temporary passwords; corrected reset email wording |
| [Demoinfo2 Tipping Service](reference/demoinfo2-tipping-service.md) | **SHELVED** — investigated microservice to extract in-game tip events for a tipping leaderboard; found infeasible (tips aren't recorded in demo files) |
| [Shoutrrr Support](reference/shoutrrr-support.md) | **PLANNED** — not built yet. Outbound push notifications via a separately-hosted Shoutrrr instance; first notification type is a match-starting-soon reminder |
| [My Team Drag-and-Drop](reference/my-team-drag-and-drop.md) | HTML5 drag-and-drop to reorder the active roster; card viewer backdrop-click dismiss |
| [Admin Tab Navigation and MVP Match View](reference/admin-tab-navigation-mvp.md) | Tab-based admin panel layout; match table with admin-side MVP selection |
| [Season Lifecycle Management](reference/season-lifecycle.md) | End-season archive, season reset, manual date-only week creation; retires season env vars |
| [Demo Mode](reference/demo-mode.md) | Env-gated demo clock override and disposable account seeding for demonstrating the season lifecycle on demand |
| [Testing Tooling](reference/testing-tooling.md) | Demo-mode season scenarios (pre-season, mid-season, season-end), a local mock OpenDota server for end-to-end ingest, and named test snapshots |
| [Frontend Framework Evaluation](reference/frontend-framework-evaluation.md) | Decision document comparing vanilla-JS vs. framework adoption, grounded in this codebase's actual constraints and the scrapped bracket-tree visualization as a worked example |
| [Kana Hub Integration Feasibility](reference/kana-hub-integration-feasibility.md) | Decision document: feasibility, blockers and options for folding Kana Cards into Kana Hub (Eggosystem) as its Dota fantasy, alongside the separate CS2 fantasy; where Dota fits in the hub's per-game structure, what a Steam-only login removes from Kana Cards, and an in-depth evaluation of a full port (architecture, data model, effort, phases, decision criteria) |
| [Container Health Check](reference/container-health-check.md) | Decision document comparing container health-reporting options; flags that the existing Compose healthcheck's `curl` dependency is likely missing from the built image |
| [DB Backup Leak Fix](reference/db-backup-leak-fix.md) | Closes a `.gitignore` gap that let two SQLite DB backup snapshots (with an admin's email + password hash) get committed to git |
| [Rate Limiting](reference/rate-limiting.md) | Per-IP request-rate limits app-wide, with stricter limits on login/register/forgot-password and a per-username failed-login lockout |
| [Roster Limit Race Fix](reference/roster-limit-race-fix.md) | Atomic conditional-UPDATE fix for a race condition that let concurrent requests exceed the active-roster limit |
| [Roster Mutation Rate Limiting](reference/roster-mutation-rate-limiting.md) | Per-user rate limiting on roster activate/deactivate/swap/reorder, plus a frontend in-flight guard, closing a cheap DoS vector |
| [Assists Scoring Fix](reference/assists-scoring-fix.md) | Fixes assists contributing zero points to fantasy scoring despite being captured, ingested, and displayed |
| [Stored Card Points](reference/stored-card-points.md) | Card points stored per match and summed by every view, so My Team and the leaderboards agree and pages stop recalculating per request |
| [Points Rounding](reference/points-rounding.md) | One server-side rounding rule (one decimal, half away from zero, on the decimal value) for every points number, so My Team, leaderboards, Weekly Report and the Twitch panel agree |
| [Weekly Recap Animations](reference/weekly-recap-animations.md) | Card-by-card reveal in the Weekly Report's My roster column: raw points count up, then rarity, modifier and MVP bonuses are highlighted and added, from a per-card points breakdown |
| [Password Manager Autofill](reference/password-manager-autofill.md) | Login, registration, password reset, change-password and admin re-login as real forms with `autocomplete` hints, so password managers fill and save the right fields |
| [Flicker-Free Tab Switching](reference/flicker-free-tab-switching.md) | Tabs and the Weekly Report update only what changed: `renderIfChanged`, no loading placeholders over existing content, quiet same-tab refresh, and a fixed Weekly Report frame with an in-memory week cache |
| [Twitch Extension Policy Compliance](reference/twitch-extension-policy-compliance.md) | For Twitch policy 4.5: live info for every viewer, one-button Join creating a Twitch soft account, card draws, collection and roster in the panel, MVP drops to soft accounts; link codes leave the extension (Part 1, #157) |
| [Twitch Account Connection](reference/twitch-account-connection.md) | Website "Connect Twitch" through Twitch's sign-in (OpenID Connect), merging a Twitch soft account into the website account after confirmation, and retiring the old link codes (Part 2, #160) |
| [Steam Login](reference/steam-login.md) | Steam OpenID 2.0 sign-in alongside passwords, with a `LOGIN_METHOD` switch (password / both / steam_signup: Steam-only account creation from S17), Link Steam for existing accounts, and admins from `SEED_ADMIN_STEAM_IDS` (#150) |
| [Impersonation Hardening](reference/impersonation-hardening.md) | Case-insensitive unique usernames, reserved words with look-alike matching, an admin badge, profiles that hide self-reported player ids and avatars, and a rename cooldown (#169) |
| [Twitch Incident Runbook](reference/twitch-incident-runbook.md) | (#160) What to do if the Twitch sign-in, the developer account or a merge goes wrong: kill switches, secret rotation, audit review, merge reversal, player communication |
| [Automatic Bench Substitution](reference/automatic-bench-substitution.md) | After a week ends, active cards whose player played 0 matches are swapped for the highest bench card whose player did; bench saved at lock; admin re-run |
| [Forgot Password Cooldown](reference/forgot-password-cooldown.md) | Per-account cooldown on password-reset emails, independent of source IP, closing the remaining gap after issue #121's per-IP limit |
| [Password Reset Token Flow](reference/password-reset-token-flow.md) | Replaces the forgot-password flow's immediate password-overwrite with a single-use, expiring reset token — a username alone no longer changes anyone's real password |
| [Session Revocation](reference/session-revocation.md) | Password change/reset, log out everywhere and admin force-logout end existing sessions (first via a per-user session version, now by deleting server-side session rows; see Longer Sessions) |
| [Longer Sessions](reference/longer-sessions.md) | Server-side sessions (hashed random IDs) with 14-day idle / 30-day absolute limits for players, 2 h / 12 h plus password re-entry for destructive actions for admins, real logout, and a sessions list on Profile |
| [HTTPS Enforcement](reference/https-enforcement.md) | Fails loudly at startup if `HTTPS_ONLY` isn't set outside local dev, and documents the TLS/reverse-proxy requirement for production prominently |
| [Profile Requires Login](reference/profile-requires-login.md) | Gates `GET /profile/{user_id}` behind an authenticated session, closing an anonymous user-enumeration vector |
| [OpenDota Parse Retry](reference/opendota-parse-retry.md) | Re-fetches matches ingested before OpenDota parsed them, replaces their stat rows once parsed, and requests a parse from OpenDota |
| [Unparseable Match Handling](reference/unparseable-match-handling.md) | Parse status per match, partial-stat markers for players, admin retry-parse, auto-flagging of stuck matches, and admin exclusion of unparseable matches from scoring |
