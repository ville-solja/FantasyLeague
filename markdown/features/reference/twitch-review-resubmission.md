# Twitch Review Resubmission

Fixes for the September 2026 Twitch review rejection of the Kana-Cards Extension. The review failed because the Extension did not load (404) and the chat capability was not described in the listing. Used by the operator when resubmitting. The durable submission checklist lives in [Twitch Extension Review Submission](twitch-extension-review-submission.md).

---

## Rejection reasons

| Guideline | Reviewer finding | Fix |
|---|---|---|
| 1.2 | "Extension doesn't load (404)" | Correct console Asset Hosting paths, allowlist the EBS for fetch, verify in Hosted Test before submitting |
| 4.2 | Chat capability enabled but not described | Add a Twitch Chat paragraph to the listing description; mirror it in `config.html` and `panel.html` |

## Diagnosis of the 404

Checked at planning time and ruled out:

- **Zip layout.** `twitch-extension-1.1.5.zip` is flat, with every referenced local asset at the root.
- **Backend routing.** `https://kana-cards.com/twitch/*` answers 422 without auth, not 404.
- **CORS.** A preflight from an `*.ext-twitch.tv` origin succeeds.
- **Helper script and legal pages.** All return 200.

Remaining suspects are all dev-console settings: the Asset Hosting viewer paths, the Allowlist for URL Fetching Domains, and whether the version was in Hosted Test when submitted.

## Required console settings

| Setting | Value |
|---|---|
| Panel Viewer Path | `panel.html` |
| Config Path | `config.html` |
| Live Config Path | `live_config.html` |
| Allowlist for URL Fetching Domains | `https://kana-cards.com` |
| Capabilities → Chat | Enabled |

## Chat behaviour to disclose

One message each time the broadcaster confirms a match MVP, including re-selections, posted by `backend/twitch.py` via `POST https://api.twitch.tv/helix/extensions/chat`. It contains the MVP player's name and the Kanaliiga Fantasy usernames of token-drop winners, or a note that the drop pool was empty. The Extension never reads, stores or moderates chat.

## Package self-check

`bash twitch-extension/package.sh <version>`:

- exits non-zero with a usage message when no version is given (it no longer defaults to `1.0.0`)
- exits non-zero with "already exists — bump the version" when `twitch-extension-<version>.zip` exists, so a submitted archive is never updated in place
- exits non-zero naming the file (e.g. `panel.html references missing.js, which is not packaged.`) when any local `src`/`href` in a packaged HTML file is not in the `FILES` array; absolute `http(s)://` and protocol-relative `//` URLs are ignored
- on success, prints the Asset Hosting paths and the URL Fetching allowlist entry from the table above

`backend/tests/test_twitch_review_resubmission.py` enforces the same rules in CI: it runs `package.sh` against a `tmp_path` copy of `twitch-extension/` (skipped if `zip` is not installed), statically checks every packaged HTML file's local references against `FILES`, checks the Twitch helper is the first `<script>` in each, checks `dev-harness.html` and `package.sh` are not packaged, and checks the chat disclosure copy in the listing description, `config.html` and `panel.html`.

## Chat disclosure copy

- Listing description: a **Twitch Chat** paragraph in [Twitch Extension Review Submission](twitch-extension-review-submission.md#listing-copy).
- `twitch-extension/config.html`: one sentence under "For broadcasters" describing the MVP chat announcement.
- `twitch-extension/panel.html`: a note in the unlinked view (`#chat-note`) that a drop winner's Kanaliiga Fantasy username is posted in chat.

## Resubmission

Package `twitch-extension-1.1.6.zip` (eight files at the zip root). The operator console steps are:

1. Create version `1.1.6` and set the Asset Hosting paths.
2. Add `https://kana-cards.com` to Allowlist for URL Fetching Domains and confirm Chat is enabled.
3. Upload the zip and move the version to Hosted Test.
4. Verify all three views load with no 404 and no CSP violation, confirm an MVP, and check the chat message matches the listing description.
5. Paste the updated description and resubmit. Optionally reply to the review email summarising both fixes.

Outcome: pending the operator's console changes and Twitch's re-review.
