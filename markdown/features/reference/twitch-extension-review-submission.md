# Twitch Extension Review Submission

Complete submission package for the Kanaliiga Kana-Cards Twitch Extension: ready-to-use listing
copy, required disclosures, and a step-by-step checklist covering every section of Twitch's
"Submit for Review" form, plus the fixes made to satisfy
[Extension Guidelines & Policies](https://dev.twitch.tv/docs/extensions/guidelines-and-policies/)
in the process.

**Package to submit:** `twitch-extension-1.1.5.zip` (or later) — the first version with the
XSS fix below. Do not submit an earlier version.

---

## Submission checklist (work through in order)

- [ ] **Version** — upload `twitch-extension-1.1.5.zip`, confirm it in Local/Hosted Test first
- [ ] **Listing copy** — name, summary, and description (below)
- [ ] **Category** — below
- [ ] **Icon & screenshots** — below (verify existing assets meet the size specs)
- [ ] **Legal** — Privacy Policy and Terms of Service URLs (already published, below)
- [ ] **Support contact** — an email or URL viewers/reviewers can reach you at
- [ ] **Capabilities declared** — Extension Configuration Service, Chat (see disclosures below)
- [ ] **Notes for reviewer** — paste the EBS URL disclosure block verbatim (below)
- [ ] **Testing instructions** — paste the numbered steps-to-reproduce below (Twitch's form asks
      for this explicitly, separate from "Notes for reviewer")
- [ ] **Test setup** — a live/active review channel with real match data, plus a working test
      account (below) — arrange this *before* clicking submit, not after
- [ ] Submit

---

## Listing copy

**Name:** Kanaliiga Kana-Cards

**Summary** (one line):
> Link your Kanaliiga Fantasy account to receive live token drops when the broadcaster names a
> match MVP.

**Description** (full):
> This extension connects your stream to the Kanaliiga Fantasy League (kana-cards.com).
>
> **For viewers:** the panel below the stream lets you link your Kanaliiga Fantasy account. Once
> linked, you're eligible for token drops whenever the broadcaster selects a match MVP — no
> purchase or payment involved.
>
> **For broadcasters:** MVP selection and token drops live in Stream Manager → Quick Actions.
> Open Stream Manager, find the Kana Cards tile in the Quick Actions bar, and use it during or
> after a match to name the MVP and trigger a chat announcement plus a token drop to linked
> viewers currently watching.

This wording is deliberately consistent with `twitch-extension/config.html`'s existing broadcaster
setup copy — keep them in sync if either changes.

## Category

**Panel extension.** No overlay or component/mobile-specific placement is used.

Suggested category: **Companion / Fan Engagement** (or the closest equivalent in the current dev
console taxonomy — Twitch's category list changes occasionally, pick whichever best matches "fan
engagement / loyalty" rather than a game-specific category, since the underlying league can be
any Dota 2 league, not just Kanaliiga).

## Icon & screenshots

Not stored in this repo — sourced separately in the dev console. Verify existing assets meet
current spec before submitting (check the live dev console for exact current numbers, as Twitch
periodically adjusts these):

| Asset | Typical requirement |
|---|---|
| Extension icon | 24×24, 100×100, and 300×300 PNG |
| Discovery/screenshots | 800×450 PNG or JPG, at least 2 |
| Legal/panel preview | as prompted in the console |

Screenshots must **accurately represent current functionality** per Twitch's guidelines — capture
both the viewer panel (linked and unlinked states) and the broadcaster's live_config MVP-selection
flow, not just the marketing/config page. `assets/logo_kanaliiga_primary.png` is available in this
repo as a possible source image if a fresh icon render is needed, though the extension's icon is
configured once in the dev console independent of code version and does not need to change for
this submission unless it's currently missing or undersized.

## Legal

Twitch's Extension Settings "Legal" tab requires a Privacy Policy URL (and typically Terms of
Service) since this Extension links a Twitch identity to a Service account. Both are published
and reachable directly, no login required:

- Privacy Policy: `https://kana-cards.com/privacy.html`
- Terms of Service: `https://kana-cards.com/terms.html`

## Support contact

Provide an email address or URL the reviewer (and, once live, viewers) can reach for support
questions. Use whatever the operator's existing support channel is — this repo has no support
email/URL configured anywhere in code, so this must be supplied manually at submission time.

---

## EBS URL disclosure (required — paste into "Notes for reviewer")

Twitch's guidelines require **all externally-fetched URLs to be disclosed with the
submission**. This extension does **not** hardcode its backend URL in the submitted package —
`twitch-extension/extension.js` reads it at runtime from the Twitch Extension Configuration
Service (`Twitch.ext.configuration.global`), so a reviewer cannot discover it just by reading
the zip's source. **Paste this into the submission's "Notes for reviewer" field:**

> The Extension's backend (EBS) URL is not hardcoded in this package. It is read at runtime from
> the Extension Configuration Service's global config segment (`ebs_url` key), set by the
> developer via `twitch-extension/set-ebs-url.sh`. The currently configured EBS URL is
> **`https://kana-cards.com`**. All Extension frontend network calls go to this single host, at
> the paths listed below. No other external domain is contacted from the Extension's own
> frontend code (the Twitch Extension Helper script itself is loaded from Twitch's own
> `extension-files.twitch.tv` CDN, per Twitch's required inclusion).
>
> Privacy Policy: https://kana-cards.com/privacy.html — Terms of Service: https://kana-cards.com/terms.html

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
are the Service's own internal, non-monetary virtual currency (see Monetization below), unrelated
to Twitch Bits.

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
- Make sure the review channel is actually live at review time — Twitch requires this
  independent of anything above

## Steps to reproduce (paste into "Testing Instructions")

Two independent flows to exercise — viewer linking/token-drop eligibility, and broadcaster MVP
selection. Both use the same review channel; the broadcaster steps trigger the viewer-visible
result in the first flow, so run flow 1 first and leave that viewer account linked and eligible.

**Flow 1 — Viewer: link account, become drop-eligible**
1. As the test viewer account, open the review channel and expand the Kana Cards panel below the
   video player.
2. Unlinked state: the panel shows "Link your account," a 6-character code field, and
   instructions to visit kana-cards.com.
3. In a separate tab, log into the provided kana-cards.com test account → Profile → Generate
   Twitch Code. Copy the 6-character code (expires in 10 minutes).
4. Back in the Twitch panel, enter the code and click **Link**.
   **Expected:** the panel switches to the linked view, showing the account's username and
   current token balance.
5. Leave the panel open (a heartbeat keeps the account eligible for token drops roughly every
   55 seconds while it's open).

**Flow 2 — Broadcaster: select MVP, trigger token drop and chat announcement**
1. As the broadcaster, go to the Twitch Creator Dashboard → **Stream Manager**.
2. In the **Quick Actions** bar at the bottom, click the **Kana Cards** tile (only visible while
   live or in Stream Manager — it will not appear on the public channel page).
3. Click **Select match MVP**.
4. A list of recent series (team1 vs team2), sourced from real ingested match data, appears —
   select one.
5. Select the specific match within that series.
6. A grid of players from both teams appears — select the match MVP, then click
   **Confirm MVP & Drop Tokens**.
   **Expected, all at once:**
   - The channel's Twitch chat receives an announcement: `Match MVP: <PlayerName>! ...`
   - Every currently-eligible linked viewer (anyone who completed Flow 1 and still has the panel
     open) receives +1 token
   - The test viewer account from Flow 1 shows the incremented token balance next time its panel
     refreshes or reopens
7. Optional: re-open **Select match MVP** and re-confirm the same match with a different player.
   **Expected:** the MVP name updates, but tokens are **not** dropped a second time for that
   match (idempotent by design).

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
