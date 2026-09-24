# Plan: Twitch Extension Review Resubmission

## Context
Twitch review placed the Kana-Cards Extension under "Pending Approval" for two reasons.
**1.2:** the reviewer could not load the Extension and saw a 404.
**4.2:** the Chat Capabilities capability is enabled, but the listing description does not say what the Extension does in chat.

Planning-time investigation narrowed the 404 to Twitch's side of the hosting chain, not the backend:

- The `twitch-extension-1.1.5.zip` layout is flat. `panel.html`, `config.html`, `live_config.html` and every local script and stylesheet they reference sit at the zip root.
- The production EBS at `https://kana-cards.com` routes `/twitch/*`. `GET /twitch/status` and `GET /twitch/matches/current` return 422 without an `Authorization` header, not 404. A CORS preflight from an `*.ext-twitch.tv` origin returns 200 with `access-control-allow-origin: *`.
- `https://extension-files.twitch.tv/helper/v1/twitch-ext.min.js`, `/privacy.html` and `/terms.html` all return 200.
- No doc in this repo covers the dev console's **Asset Hosting** paths (Panel Viewer Path, Config Path, Live Config Path) or the **Allowlist for URL Fetching Domains**. A wrong or empty viewer path makes Twitch's CDN return 404 for the Extension iframe, which matches the review error exactly. A missing fetch allowlist entry makes Twitch's Content Security Policy (CSP) block every EBS call, which is the other failure mode the review email names.

**Assumption:** the root cause is console configuration: asset paths, the fetch allowlist, or a version not moved to Hosted Test before submission. It is not a code defect. The code-side work is therefore a packaging self-check that prevents recurrence, plus a version bump, since Twitch requires a new version for resubmission. The console fixes are manual operator steps that this plan documents as a checklist.

For 4.2, the chat capability is genuinely used. `backend/twitch.py` posts one message each time the broadcaster confirms a match MVP, re-selections included, through `POST /helix/extensions/chat`, listing the MVP player and the Kanaliiga Fantasy **usernames** of drop winners. The fix is to disclose this in the listing description, not to disable the capability.

## User Stories

### Reviewer Can Load Every Extension View
**User story**
As a Twitch Extension reviewer, I want every view of the Extension to load from Twitch's hosted CDN so that I can complete a full functional review.

**Acceptance criteria**
- The dev console's Asset Hosting paths are exactly `panel.html` (Panel Viewer Path), `config.html` (Config Path) and `live_config.html` (Live Config Path), with no leading slash or folder prefix
- The submitted version is uploaded and moved to **Hosted Test** before submission, and all three views load in Hosted Test without a 404 on a real channel
- The panel view reaches either the unlinked or linked state, never the "not configured" error, when loaded in Hosted Test
- The submitted zip version is higher than `1.1.5`

### EBS Domain Allowlisted for Fetch
**User story**
As the Kanaliiga developer, I want the backend domain allowlisted in the dev console so that Twitch's Content Security Policy does not block the Extension's API calls.

**Acceptance criteria**
- The console's **Allowlist for URL Fetching Domains** contains `https://kana-cards.com`
- No other external domain is fetched by the Extension frontend, so no other entry is needed
- In Hosted Test, the browser console shows no CSP `connect-src` violation when the panel calls `/twitch/status`
- The submission checklist lists the allowlist step before "Submit"

### Package Self-Check Before Upload
**User story**
As the Kanaliiga developer, I want the packaging script to fail when an HTML file references a local file missing from the zip so that a broken package never reaches review.

**Acceptance criteria**
- `bash twitch-extension/package.sh <version>` exits non-zero and names the missing file if any `src` or `href` in a packaged HTML file points to a local file not in the package
- The script exits non-zero if no version argument is given, instead of silently defaulting to `1.0.0`
- The script exits non-zero if the output zip already exists, instead of updating a previously submitted archive in place
- On success, the script prints the exact console Asset Hosting paths and the fetch allowlist entry to set
- A pytest test asserts every local asset referenced by `panel.html`, `config.html` and `live_config.html` is in the package file list, and that the Twitch helper script is the first `<script>` in each

### Chat Usage Disclosed in Listing
**User story**
As a Twitch reviewer and as a viewer, I want the Extension description to explain what it posts in chat so that I know how it interacts with Twitch Chat.

**Acceptance criteria**
- The listing description has a dedicated chat paragraph. It says the Extension posts one message to the channel's chat when the broadcaster confirms a match MVP, and never at any other time
- The paragraph states the message contents: the MVP player's name, and the Kanaliiga Fantasy usernames of viewers who won the token drop, or a note that no linked viewers were in the pool
- The paragraph states the Extension does not read, store or moderate chat, and re-selecting the MVP for a match that already had a token drop does not drop tokens again
- `twitch-extension/config.html`'s broadcaster copy mentions the chat announcement, consistent with the listing description
- The panel's unlinked view tells viewers that linking can show their Kanaliiga username in chat if they win a drop

## Implementation

### Critical Files
| File | Change |
|---|---|
| `twitch-extension/package.sh` | Require a version argument, refuse to overwrite an existing zip, verify local HTML references, print console asset paths and allowlist entry |
| `twitch-extension/config.html` | Add one sentence on the MVP chat announcement to the broadcaster section |
| `twitch-extension/panel.html` | Add one sentence to the unlinked view saying drop winners' usernames are posted in chat |
| `backend/tests/test_twitch_review_resubmission.py` | New: static checks on the extension HTML files against the package file list, package.sh behaviour (run in a tmp copy), and the chat disclosure copy |
| `markdown/features/reference/twitch-extension-review-submission.md` | Rewrite listing description with chat paragraph, add Asset Hosting and URL allowlist checklist items, bump the package version, add a rejection-history note |
| `markdown/features/core/twitch-extension.md` | Add Asset Hosting paths and URL Fetching allowlist rows to the Prerequisites table |
| `markdown/features/reference/twitch-review-resubmission.md` | Fill in stub with the diagnosis and final outcome |

No backend endpoint, model or env var changes. No migration needed.

### Step 1 — Harden `package.sh`
Keep the single `FILES=(...)` array as the source of truth. Before zipping:

```bash
VERSION=${1:?"Usage: package.sh <version>  (e.g. 1.1.6)"}
OUT="twitch-extension-${VERSION}.zip"
[ -e "$SCRIPT_DIR/$OUT" ] && { echo "ERROR: $OUT already exists — bump the version."; exit 1; }

# Every local src/href in a packaged HTML file must be in FILES.
for html in "${FILES[@]}"; do
  [[ "$html" == *.html ]] || continue
  for ref in $(grep -oE '(src|href)="[^"]+"' "$html" | cut -d'"' -f2 | grep -vE '^(https?:)?//'); do
    printf '%s\n' "${FILES[@]}" | grep -qx "$ref" || { echo "ERROR: $html references $ref, which is not packaged."; exit 1; }
  done
done
```

After zipping, replace the stale "Next steps" block, which still describes a hand-written Helix PUT that `set-ebs-url.sh` now wraps, with:

```
Dev console → Version → Asset Hosting:
  Panel Viewer Path:  panel.html
  Config Path:        config.html
  Live Config Path:   live_config.html
Dev console → Version → Capabilities → Allowlist for URL Fetching Domains:
  https://kana-cards.com
Upload the zip, move the version to Hosted Test, verify all three views, then submit.
```

### Step 2 — Static package test
Add `backend/tests/test_twitch_review_resubmission.py`. Parse `FILES` from `package.sh` with a regex, parse each packaged HTML file with `html.parser.HTMLParser`, and assert:
- every non-absolute `src`/`href` is in `FILES`
- the first `<script>` in each HTML file is the Twitch helper URL
- `dev-harness.html` and `package.sh` are not in `FILES`

Standard library only. The test resolves paths from the repo root so it runs from `backend/` like the rest of the suite.

### Step 3 — Chat disclosure copy
Replace the **Description** block in `twitch-extension-review-submission.md` with a version that adds a "Twitch Chat" paragraph:

> **Twitch Chat:** when the broadcaster confirms a match MVP, the extension posts one message to the channel's chat, for example: "Match MVP: PlayerName! Token drop winners (+1 Kana Tokens): user1, user2". The names listed are the winners' Kanaliiga Fantasy usernames. If no linked viewers are watching, the message says so instead. Changing the MVP for a match that already had a drop does not drop tokens again. The extension posts nothing else, and it never reads, stores or moderates chat messages.

Mirror a one-line version in `config.html` under "For broadcasters", and a one-line viewer note in `panel.html`'s unlinked view. Keep the existing sync note in the submission doc pointing at both files.

### Step 4 — Package and bump the version
Run `bash twitch-extension/package.sh 1.1.6`. Update every `1.1.5` reference in the submission doc's header and checklist to `1.1.6`, keeping the note that `1.1.5` is the first version with the XSS fix.

### Step 5 — Console checklist and rejection history
In `twitch-extension-review-submission.md`:
- Add checklist items before "Submit": **Asset Hosting paths**, **URL Fetching allowlist**, and **Hosted Test verification**. The verification item says to load all three views on the review channel, open browser dev tools, and confirm no 404 and no CSP violation.
- Change the capabilities item to reference the new chat paragraph.
- Add a short "Review history" section recording the 2026-09 rejection, its two reasons, and what fixed each.

In `core/twitch-extension.md`, add the Asset Hosting and URL allowlist rows to the Prerequisites table. The "Common mistake" column should note a folder prefix such as `twitch-extension/panel.html` or a leading `/`.

### Step 6 — Operator console actions (manual, not code)
1. Open the new version in the dev console and set the Asset Hosting paths from Step 1.
2. Add `https://kana-cards.com` to Allowlist for URL Fetching Domains.
3. Confirm Chat is still enabled under Capabilities.
4. Upload `twitch-extension-1.1.6.zip` and move to Hosted Test.
5. Verify, then paste the updated description and resubmit. Optionally reply to the review email summarising both fixes.

## Verification
- `cd backend && python -m pytest tests/test_twitch_review_resubmission.py -v` passes.
- Temporarily add `<script src="missing.js">` to `panel.html`. Both `package.sh` and the pytest test must fail naming `missing.js`. Revert afterwards.
- `bash twitch-extension/package.sh` with no argument fails with the usage message. Re-running with an existing version fails with the "already exists" message.
- `unzip -l twitch-extension/twitch-extension-1.1.6.zip` lists exactly the eight packaged files at the zip root.
- In Hosted Test on the review channel, the panel, config and live config views load. Dev tools show no 404 and no CSP `connect-src` violation. The panel reaches the unlinked or linked state.
- Confirm an MVP in Hosted Test and check the chat message matches the wording in the listing description.
- No migration or seed step is needed.
