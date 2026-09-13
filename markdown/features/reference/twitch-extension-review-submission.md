# Twitch Extension Review Submission

Checklist and disclosure notes for submitting the Kanaliiga Kana-Cards Twitch Extension for
Twitch review (moving a version out of Hosted Test toward public release), plus the fixes made
to satisfy Twitch's [Extension Guidelines & Policies](https://dev.twitch.tv/docs/extensions/guidelines-and-policies/)
in the process.

---

## EBS URL disclosure (required — read this before submitting)

Twitch's guidelines require **all externally-fetched URLs to be disclosed with the
submission**. This extension does **not** hardcode its backend URL in the submitted package —
`twitch-extension/extension.js` reads it at runtime from the Twitch Extension Configuration
Service (`Twitch.ext.configuration.global`), so a reviewer cannot discover it just by reading
the zip's source. **State this explicitly in the submission's "Notes for reviewer" field:**

> The Extension's backend (EBS) URL is not hardcoded in this package. It is read at runtime from
> the Extension Configuration Service's global config segment (`ebs_url` key), set by the
> developer via `twitch-extension/set-ebs-url.sh`. The currently configured EBS URL is
> **`https://kana-cards.com`**. All Extension frontend network calls go to this single host, at
> the paths listed below. No other external domain is contacted from the Extension's own
> frontend code (the Twitch Extension Helper script itself is loaded from Twitch's own
> `extension-files.twitch.tv` CDN, per Twitch's required inclusion).

### Endpoints the Extension frontend calls (all under `https://kana-cards.com`)

| Path | Method | Called from | Purpose |
|---|---|---|---|
| `/twitch/status` | GET | `panel.js` | Whether the viewer's Twitch session is linked to a Fantasy account; token balance |
| `/twitch/heartbeat` | POST | `extension.js` (`startHeartbeat`) | Keeps a linked viewer in the token-drop eligibility pool (~every 55s while the panel is open) |
| `/twitch/link` | POST | `panel.js` | Consumes the one-time linking code the viewer generated on kana-cards.com |
| `/twitch/matches/current` | GET | `live_config.js` | Broadcaster-only: recent series/matches with player stats, for MVP selection |
| `/twitch/mvp` | POST | `live_config.js` | Broadcaster-only: sets a match's MVP, triggers the token drop and chat announcement |

`POST /twitch/link-code` also exists on the backend but is called from the **main kana-cards.com
website** (session-authenticated), never from the Extension frontend — it generates the code a
viewer then enters into the panel.

## Chat capability disclosure

The Extension uses Twitch's Extension Chat capability to post one message when a broadcaster
confirms a match MVP, e.g.:

> `Match MVP: PlayerName! Token drop winners (+1 tokens): viewer1, viewer2`

No other chat activity is read, stored, or posted. This does not use Twitch Bits — "tokens" here
are the Service's own internal, non-monetary virtual currency (see Legal below), unrelated to
Twitch Bits.

## Legal pages

Twitch's Extension Settings "Legal" tab requires a Privacy Policy URL (and typically Terms of
Service) before submission, since this Extension links a Twitch identity to a Service account.
Both are now published and reachable directly (no login required):

- Privacy Policy: `https://kana-cards.com/privacy.html`
- Terms of Service: `https://kana-cards.com/terms.html`

## Monetization / loot-box compliance

The card-draw mechanic uses weighted-random rarity, funded entirely by the Service's own
"tokens." Tokens **cannot be purchased with real money anywhere in the Service** (confirmed: no
payment/checkout code path exists in `backend/`) and have no cash-out or resale path. This
satisfies Twitch's requirement that randomized rewards are permitted only when the items involved
have no monetary value.

## Reviewer test setup

The Extension's real functionality (account linking, MVP selection, token drops) only has
something to show when: (a) a viewer account exists on kana-cards.com to generate a linking
code, and (b) at least one match with ingested player stats exists for `live_config.js`'s MVP
flow to list. Per Twitch's requirement that *"all submitted review channels must be live during
the time of review"* and third-party setup must be ready on that channel:

- Provide the reviewer a working kana-cards.com test account and a fresh linking code (codes
  expire after 10 minutes — generate one right before the review session, not in advance)
- Schedule the review during an active match week where `GET /twitch/matches/current` returns at
  least one series — an idle/off-season review will show empty states throughout and give the
  reviewer nothing to validate

## Security fix made for this submission

`live_config.js` (broadcaster MVP selection) built HTML by string-concatenating team and player
names directly into `innerHTML`. Those names come from OpenDota/Steam data ingested verbatim
with no server-side sanitization (`backend/ingest.py`), so this was a real stored-XSS risk —
also a direct violation of Twitch's *"DOM injection security"* requirement (*"Data from AJAX
requests must be validated and processed before DOM insertion"*). Fixed by adding an `_escHtml()`
helper to `extension.js` (mirroring `frontend/app-globals.js`'s existing helper) and escaping
every untrusted name before it's concatenated into an HTML string, in `twitch-extension-1.1.5`.

## Confirmed compliant, no change needed

- No Flash, no iframes, unminified human-readable JS, package well under the 1MB mobile load cap
- Twitch Extension Helper script is the first `<script>` in every real front-end HTML file
  (`panel.html`, `config.html`, `live_config.html`)
- No off-site links in the Extension's own HTML (account-linking instructions are plain text, not
  a clickable redirect)
- No elevated identity request (`requestIdShare`) — only the default opaque per-extension user ID
  plus the account's own one-time linking code are used
- No user-submitted content is shown to other users anywhere in the Extension, so the
  user-generated-content moderation rules don't apply
