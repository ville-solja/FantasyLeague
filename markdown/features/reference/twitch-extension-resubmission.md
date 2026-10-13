# Twitch Extension Resubmission (1.3.0)

Version 1.3.0 is the Kana Cards extension's submission for review after the 1.1.7 rejection under policy 4.5. This document records what changed in the submission and why. The submission steps themselves are in [Twitch Extension Review Submission](twitch-extension-review-submission.md). Resolves GitHub issue #195.

---

## Version

1.3.0 is a new version number. 1.2.0 and 1.2.1 were used in the console for testing only and are not submitted. The package is built with `bash twitch-extension/package.sh 1.3.0 --ebs-origin https://kana-cards.com`, and production runs `TWITCH_EXTENSION_VERSION=1.3.0`. The guide's [1.3.0 change log](twitch-extension-review-submission.md#2026-10--version-130-change-log) lists every packaged file changed since 1.1.7 (commit `4c34cef`).

## Stale items fixed in the guide

Reviewers compare the listing, the disclosure and the testing steps with what they see, so each of these would have been a mismatch:

| Item | Was | Now |
|---|---|---|
| Version | `twitch-extension-1.2.0.zip` | `twitch-extension-1.3.0.zip`; 1.2.x marked test-only |
| Listing, tokens | "Tokens for draws come from a weekly grant and from MVP drops" to viewers "currently watching" (no mention of the starter tokens a new player sees first) | Starter tokens on Join; the MVP drop gives one token each to up to 20 (`TWITCH_DROP_MAX`) joined viewers with the panel open, picked at random, new players after a waiting period; plus one each match week. The weekly token is real: `auto_lock_weeks` (`backend/weeks.py`) gives every account +1 when a week locks, and the panel's draw note says so |
| EBS disclosure | "The backend URL is not hardcoded" | Allowed origins are fixed in the package at build time (`ebs-origins.js`, `EBS_ALLOWED_ORIGINS`, written by `package.sh`, #164); the configured `ebs_url` is used only when its origin is one of them |
| Endpoint table | No `/twitch/check` or `/twitch/ping` | Every `/twitch/...` path the packaged files call, including the configuration page's Connection check |
| Images | Not disclosed | Team logos load only from `https://` URLs on the Steam CDN hosts (`logo_hosts.DEFAULT_LOGO_HOSTS`) |
| Checklist | No production deploy, Panel Height, Image Domains or go/no-go | Ordered: production deploy (backup, then migration 038), env vars, drop age 0 for the review window, Extension Settings (Configuration Service, empty Developer Writable Channel Segment Version), the version upload, the global `ebs_url`, Asset Hosting and Panel Height 500, URL Fetching and Image Domains allowlists, Chat and Request Identity Link, approved review channel, Connection check, Hosted Test, Admin › Users › Twitch status green (Connect Twitch and Steam warnings explained), Submit, then the drop age set back |
| Testing instructions | Flows 1–4 written for 1.2.0 | Flows 1–5 in the panel's current wording, a note on scrolling and `E-…` codes, and a Connection check flow |
| Reviewer test setup | No drop-age note | A new account joins MVP drops `TWITCH_DROP_MIN_ACCOUNT_AGE_HOURS` (default 24) after joining (#171), so the checklist sets it to 0 for the review window and back after the review |
| Screenshots | Generic list | The five views to retake for 1.3.0 |

`package.sh` now also prints `Dev console → Version → Capabilities → Allowlist for Image Domains: see Admin › Users › Twitch status` after the Panel Height reminder, on success only.

## Drift tests

`backend/tests/test_issue_195_twitch_extension_resubmission.py` keeps the guide in step with the code:

- **Endpoints:** extracts the `/twitch/...` string literals from `panel.js`, `extension.js`, `live_config.js` and `config.js` (a literal followed by `+ <expression>` becomes `{team_id}` or `{card_id}` by path), and compares them with the endpoint table's rows in both directions. A new panel call without a disclosure row, or a row for a path no longer called, fails CI.
- **Routes:** every table path must match a route registered in `main.app.routes` that accepts the row's method (the catch-all `/twitch/{rest:path}` 404 route does not count).
- **Images:** the disclosure names every host in `DEFAULT_LOGO_HOSTS`.
- **Testing flows:** every double-quoted expected result in the Steps section must appear in the packaged files (`<...>` placeholders match anything).
- **Listing, checklist, change notes:** no "weekly grant" phrase in the listing; the checklist items are present and in order; the "Changes since the last review" block has no `#<digits>` references; each 1.3.0 change log row names a file `package.sh` packages.

## Changes since the last review

The guide has a paste-ready "Changes since the last review" block for Notes for reviewer. It says the extension no longer requires or mentions any external login, that everything is played in the panel with the Twitch login, and that the identity share is optional, then lists the visible changes in plain words with no internal issue numbers. The 1.3.0 change log under Review history keeps the issue numbers for the team.
