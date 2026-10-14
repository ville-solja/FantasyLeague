# Plan: Twitch Extension Resubmission (1.3.0)

## Context
The last version submitted for review, 1.1.7, was rejected under policy 4.5: the panel required a login on an external site. Issue #157 rebuilt the panel as a game played entirely inside Twitch (1.2.0). The 1.2.x versions were then only used for testing. Since then these have landed:
- #160: Connect Twitch on the website, with the soft-account merge
- #163 and #164: hardening, and the backend origins baked into the package
- #171: panel abuse limits
- #175: approved streamers
- #180: reason codes, Connection check and build stamp
- the setup follow-ups
- #187: uniform starter tokens
- #191: the panel fits Twitch's height

Issue #195 asks to prepare the next submission so it passes. That means the submission guide (`markdown/features/reference/twitch-extension-review-submission.md`) has to describe the build that is actually uploaded.

Several parts of the guide are stale today:
- **Version:** the guide still names `twitch-extension-1.2.0.zip`.
- **Listing:** its token sentence ("a weekly grant and MVP drops") leaves out the starter tokens a new player sees first. Panel players get `INITIAL_TOKENS` on Join, +1 per MVP drop and +1 when a match week locks (`weeks.auto_lock_weeks`). *(Corrected during `/develop`: the plan first said the weekly grant didn't exist.)*
- **Disclosure:** it says the backend URL is "not hardcoded". Since #164 the allowed origins are baked into the package (`ebs-origins.js`), and the `ebs_url` in Twitch's configuration is used only when it is one of them.
- **Endpoint table:** it is missing `/twitch/check` and `/twitch/ping`, which the configuration page has called since #180.
- **Checklist:** it doesn't cover Panel Height 500 (#191), the Allowlist for Image Domains (team logos from the Steam CDN), or the production go/no-go in Admin › Users › Twitch status.

Reviewers compare the listing, the disclosure and the testing steps with what they see, and a mismatch is a common reason for rejection. So this plan:
- brings the guide up to date for one new version, 1.3.0;
- adds tests that keep the disclosure in step with the packaged code;
- writes the reviewer's "what changed since the last review" note.

Assumptions:
- The submitted version is **1.3.0**, a new version number. 1.2.0 and 1.2.1 were used in the console for testing, and the panel changed substantially after them.
- Production gets the same build as test, packaged with `--ebs-origin https://kana-cards.com`.
- Icons and screenshots stay outside the repo, as before. The guide says which screenshots to retake, because the panel looks different from 1.1.7.

Resolves GitHub issue #195.

## User Stories

### Submission Guide Matches the 1.3.0 Build
**User story**
As the operator submitting the extension, I want the submission guide to describe exactly the build I upload so that I can fill in Twitch's form without guessing and nothing I paste contradicts the extension.

**Acceptance criteria**
- The guide's header and checklist name version `1.3.0` and the build command `bash twitch-extension/package.sh 1.3.0 --ebs-origin https://kana-cards.com`; it says 1.2.0 and 1.2.1 were test-only and are not submitted
- The checklist includes, in order:
  - the production deploy of the current `main`, with migration 038 done after `scripts/backup-db.sh`;
  - the production env vars (`TWITCH_EXTENSION_CLIENT_ID`, `TWITCH_EXTENSION_SECRET`, `TWITCH_EXTENSION_VERSION=1.3.0`);
  - **Asset Hosting** paths and **Panel Height 500**;
  - **Allowlist for URL Fetching Domains**;
  - **Allowlist for Image Domains** (the `https://` Steam CDN hosts from `backend/logo_hosts.py` `DEFAULT_LOGO_HOSTS`, or the values Admin › Users › Twitch status lists);
  - the capabilities **Chat** and **Request Identity Link**, with Configuration Service;
  - approving the review channel as a streamer;
  - the configuration page's **Connection check** passing;
  - Hosted Test on the review channel;
  - Submit.
- The guide notes that capability fields can be edited only in Local Test
- Admin › Users › Twitch status shows every check green on production before Submit; the guide says so as a go/no-go line
- `package.sh` prints a reminder after the Panel Height line: "Allowlist for Image Domains: see Admin › Users › Twitch status"

### Listing Copy Says Only What the Extension Does
**User story**
As a Twitch reviewer, I want the listing to describe the extension accurately so that what I read matches what I test.

**Acceptance criteria**
- The description no longer uses the phrase "weekly grant". It says: joining gives starter tokens, more come from MVP drops when the broadcaster confirms a match MVP, plus one token each match week
- The description still has the **Twitch Chat** paragraph, the no-purchase statement and the Leave statement (existing tests keep passing)
- The token wording matches the panel's join view ("win tokens when the broadcaster picks a match MVP") and `config.html`
- A test fails if the listing mentions "weekly grant"

### Reviewer Disclosure Matches the Packaged Code
**User story**
As a Twitch reviewer, I want every backend address and path the extension contacts disclosed so that I can verify the extension against its submission notes.

**Acceptance criteria**
- The "Notes for reviewer" EBS block says the allowed backend origins are fixed in the package at build time (`ebs-origins.js`, written by `package.sh`). The `ebs_url` from the Configuration Service is used only when its origin is one of them, and the submitted package allows only `https://kana-cards.com`
- The endpoint table lists every `/twitch/...` path called from the packaged files (`panel.js`, `extension.js`, `live_config.js`, `config.js`), including `/twitch/check` and `/twitch/ping` (configuration page, Connection check)
- The disclosure names the image hosts the panel may load team logos from (the Steam CDN hosts), and says logos are shown only from `https://` URLs
- A test extracts the `/twitch/...` paths from the packaged JS files and fails if any is missing from the guide's endpoint table, or if a table row names a path no packaged file calls. Path parameters are normalised: `{card_id}`, `{team_id}`
- A test fails if any table path has no matching route in the backend (`backend/twitch.py` or the routers)

### Testing Instructions Follow the Current Panel
**User story**
As a Twitch reviewer, I want step-by-step testing instructions that match the current panel so that I can exercise every feature in one session.

**Acceptance criteria**
- Flows cover:
  - logged out (the Live tab);
  - Join (the identity share may be declined), starter tokens shown, draw, team draw, roster change;
  - the broadcaster's MVP selection, chat message and token drop;
  - Leave;
  - the broadcaster configuration page with its Connection check showing "ok".
- Each flow states its expected result in the panel's current wording, taken from `panel.html` and `panel.js`
- A note explains that the panel scrolls within its height, and that an error shows a short code (`E-…`) the operator can look up
- The "Reviewer test setup" section names:
  - the live channel and an active match week;
  - the approved review channel;
  - `TWITCH_EXTENSION_VERSION` and Chat enabled for 1.3.0.

### Reviewer Sees What Changed Since the Rejection
**User story**
As a Twitch reviewer re-reviewing the extension, I want a short note on what changed since the 1.1.7 rejection so that I can confirm the policy 4.5 finding is resolved.

**Acceptance criteria**
- The guide has a paste-ready "Changes since the last review" block for Notes for reviewer. It must say that:
  - the extension no longer requires or mentions any external login;
  - everything is played in the panel with the Twitch login;
  - the identity share is optional.
  It lists the main visible changes in plain words, without internal issue numbers.
- "Review history" gains a "2026-10 — Version 1.3.0 change log" table: file and change, one row per packaged file changed since 1.1.7
- The screenshot guidance names the views to retake for 1.3.0:
  - the panel's Live tab, not joined;
  - Cards with a reveal;
  - Roster;
  - Settings with Leave;
  - the broadcaster's MVP selection.

## Implementation

### Critical Files
| File | Change |
|---|---|
| `markdown/features/reference/twitch-extension-review-submission.md` | Version 1.3.0; checklist; listing token wording; EBS disclosure (baked origins); endpoint table with `/twitch/check` and `/twitch/ping`; image hosts; testing flows; "Changes since the last review" block; 1.3.0 change log |
| `markdown/features/reference/twitch-extension-resubmission.md` | New: what 1.3.0 changes in the submission and why (stub now) |
| `twitch-extension/package.sh` | Print the Image Domains reminder after "Panel Height: 500" |
| `twitch-extension/config.html` | Only if its token or chat copy differs from the new listing wording |
| `markdown/features/core/twitch-extension.md` | Link the submission guide from Prerequisites; no duplicated content |
| `backend/tests/test_twitch_review_resubmission.py` | Version assertions 1.2.0 → 1.3.0 |
| `backend/tests/test_issue_195_twitch_extension_resubmission.py` | New tests (below) |
| `backend/tests/test_issue_85_split_admin_router.py` | Suite-size baseline |

No backend code, schema or env var changes.

### Step 1 — Guide: version, checklist, go/no-go
Replace 1.2.0 with 1.3.0 in the header and checklist, and note that 1.2.x was test-only. Rewrite the checklist in the order from the first story. Merge the existing Asset Hosting and URL Fetching items with the new ones, rather than adding parallel lists. Take the console field names from `markdown/features/core/twitch-extension.md` Prerequisites so both docs use the same wording.

### Step 2 — Listing and disclosure
- **Listing:** replace "a weekly grant" with the starter-on-Join, MVP-drop and one-token-per-match-week wording.
- **EBS block:** rewrite it from the #164 behaviour (`ebs-origins.js`, `EBS_ALLOWED_ORIGINS`, `ebs_url` used only when allowed).
- **Endpoint table:** add `/twitch/check` and `/twitch/ping`, called from `config.js`. Check each row's "Called from" against the code.
- **Images:** add a short "Images" line naming the Steam CDN hosts.

### Step 3 — Testing instructions and change notes
- **Flows:** update Flows 1–4 to the current copy, and add Flow 5 for the configuration page's Connection check.
- **Change notes:** add the "Changes since the last review" paste block and the 1.3.0 change log. List the packaged files changed since 1.1.7 with `git diff --stat` between the 1.1.7 commit and `main` over `twitch-extension/`, and describe each in one line.

### Step 4 — Tests
`backend/tests/test_issue_195_twitch_extension_resubmission.py`:
- **Endpoint coverage:**
  - regex `/twitch/[a-z_/]+` over the packaged JS, with a trailing `/` followed by a variable mapped to the `{param}` form;
  - compared with the paths in the guide's endpoint table (the rows between that heading and the next `##`);
  - both directions.
- **Backend routes:** every table path matches a route in `main.app.routes`, so import the app with `DEBUG=true` as other tests do.
- **Listing:**
  - no "weekly grant";
  - mentions starter tokens and MVP drops;
  - still has the chat paragraph.
- **Checklist:** contains "Panel Height", "500", "Allowlist for Image Domains", "Request Identity Link", "Connection check" and "Twitch status".
- **Images:** the EBS/image disclosure names each host in `logo_hosts.DEFAULT_LOGO_HOSTS`.
- **Change notes:** a "Changes since the last review" block exists and contains no `#<digits>` issue references.
- **Change log:** the 1.3.0 change log heading exists.
- **package.sh:** the success output contains the Image Domains reminder. Run it in a tmp copy, like the existing package.sh tests.

Update `test_twitch_review_resubmission.py`'s version tests to 1.3.0, and keep `test_issue_85`'s baseline in step.

### Step 5 — Feature doc
`twitch-extension-resubmission.md` holds:
- what changed in the submission for 1.3.0;
- the stale items fixed and why (listing accuracy, disclosure of baked origins, endpoint drift test);
- a link to the guide.

Add a row to `markdown/features/README.md` and a link from the guide's Review history ("Details: …"), as for the 1.1.6 resubmission.

## Verification
- **Tests:** `cd backend && python3 -m pytest tests/test_issue_195_twitch_extension_resubmission.py tests/test_twitch_review_resubmission.py -q`, then the full suite.
- **Package:** run `bash twitch-extension/package.sh 1.3.0 --ebs-origin https://kana-cards.com` on a clean checkout of `main`. It should print:
  - the origins and Asset Hosting paths;
  - Panel Height 500;
  - the Image Domains reminder;
  - the URL Fetching entry.
- **Rehearsal on test before submitting:**
  1. Build the same code with the test origin.
  2. Upload it as a new test version in Hosted Test.
  3. Walk Flows 1–5 from the guide word for word on the test channel, with dev tools open: no 404, no CSP violation, Connection check ok.
- **Production go/no-go:**
  - deploy `main`, running migration 038 after `scripts/backup-db.sh`;
  - set the env vars;
  - Admin › Users › Twitch status all green;
  - approve the review channel;
  - upload 1.3.0, complete the console fields, Hosted Test on the review channel, then submit with the pasted blocks.
- **Manual:** retake the screenshots listed in the guide, and check that the icon sizes meet the console's current spec.
