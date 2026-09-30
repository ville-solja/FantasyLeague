# User Stories — Index

| File | Covers |
|---|---|
| [users-and-access.md](users-and-access.md) | Registration, login, password reset, profile, header link, temporary password expiry, rate limiting, session revocation |
| [cards.md](cards.md) | Deck generation, draw, rarity, modifiers, card art, blank team-logo placeholder, player popup, mid-season top-up, dynamic card creation, team booster draws, team draw explanation and naming |
| [user-tags.md](user-tags.md) | User tag system: card stickers, leaderboard badges, admin tag management, user search, profile tag visibility |
| [team-tokens-scoring.md](team-tokens-scoring.md) | Active roster, roster limit race fix, roster mutation rate limiting, weekly lock, week history, tokens, scoring, weekly summary report, docked reveal-all control, pre-reveal winner hiding, match date display, stored per-match card points |
| [data-and-players.md](data-and-players.md) | Dota data ingestion, live-match-aware OpenDota query prioritization, OpenDota parse retry for unparsed matches, unparseable match handling (partial-stat markers, admin retry and scoring exclusion), player profile enrichment, AI bios |
| [leaderboard.md](leaderboard.md) | Season/weekly leaderboard, player/team browser, MVP visibility, weight simulation |
| [admin.md](admin.md) | User management, promo codes, scoring config, audit logs, version badge, env-based admin seeding, player pool management and card refunds, live progress for bulk player add, admin tab navigation and MVP selection, season lifecycle, demo mode, inline week editing and overlap prevention, on-demand database backups (create, list, download) |
| [twitch.md](twitch.md) | MVP selection, token drops, account linking, extension setup, MVP fantasy bonus, series window, live polling, review resubmission (asset hosting, fetch allowlist, chat disclosure), early MVP selection from live matches, chat announcement fix |
| [ux-and-polish.md](ux-and-polish.md) | Schedule tab, JSON fixtures API source, MVP schedule cache invalidation, scoring explanation, My Team layout, CI testing, How to Play tab, drag-and-drop roster ordering, card viewer backdrop dismiss |
| [deployment.md](deployment.md) | DB sustainability, versioned migrations, pre-deploy backup, container health reporting, DB backup leak prevention, HTTPS enforcement |
| [tooling.md](tooling.md) | Agent lessons log, development tooling, process diagrams, admin router organization, frontend framework evaluation, test background task isolation, technical writer skill |
| [tipping.md](tipping.md) | Demoinfo2 tipping service: demo parsing, tip event extraction, tipping leaderboard |
| [shoutrrr-support.md](shoutrrr-support.md) | *(Not yet implemented)* Outbound push notifications via a separately-hosted Shoutrrr instance; match-starting-soon reminder |
| [security-review-fixes.md](security-review-fixes.md) | Fixes from the 2026-09-26 external security review: Twitch MVP eligibility, escaping external text, reliable password reset, abuse limits, deployment hardening; security audit 3 (issue #136): cross-origin request check, username allowlist, CORS limited to Twitch, production guards and pip-audit |
