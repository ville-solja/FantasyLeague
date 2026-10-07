# Twitch Extension Review Submission

Complete submission package for the Kanaliiga Kana-Cards Twitch Extension: ready-to-use listing
copy, required disclosures, and a step-by-step checklist covering every section of Twitch's
"Submit for Review" form, the dev-console Asset Hosting and URL Fetching settings the Extension
needs to load for a reviewer, plus the fixes made to satisfy
[Extension Guidelines & Policies](https://dev.twitch.tv/docs/extensions/guidelines-and-policies/)
in the process. See [Review history](#review-history) for past rejections.

**Package to submit:** `twitch-extension-1.2.0.zip` (or later), built with
`bash twitch-extension/package.sh 1.2.0 --ebs-origin https://kana-cards.com` (since issue #164 the
package must name the backend origins the panel may call). Version `1.1.5` was the first with the XSS fix below;
`1.1.6` adds the chat disclosure copy required by the 2026-09 review; `1.1.7` adds the Live /
Stats pending labels for early MVP selection (issue #139); `1.2.0` makes the panel a complete
game on Twitch with no website login (policy 4.5, issue #157). Do not resubmit `1.1.7` or
earlier — Twitch requires a new version for every resubmission.

---

## Submission checklist (work through in order)

- [ ] **Version** — create version `1.2.0` in the dev console and upload `twitch-extension-1.2.0.zip`
- [ ] **Listing copy** — name, summary, and description (below)
- [ ] **Category** — below
- [ ] **Icon & screenshots** — below (verify existing assets meet the size specs)
- [ ] **Legal** — Privacy Policy and Terms of Service URLs (already published, below)
- [ ] **Support contact** — an email or URL viewers/reviewers can reach you at
- [ ] **Capabilities declared** — Extension Configuration Service, Chat, and **Request Identity
      Link** (the panel's Join asks for Twitch's identity share). Chat use is disclosed in the
      **Twitch Chat** paragraph of the listing description (below) — the reviewer checks it
- [ ] **Notes for reviewer** — paste the EBS URL disclosure block verbatim (below)
- [ ] **Testing instructions** — paste the numbered steps-to-reproduce below (Twitch's form asks
      for this explicitly, separate from "Notes for reviewer")
- [ ] **Test setup** — a live/active review channel with real match data, plus a working test
      account (below) — arrange this *before* clicking submit, not after
- [ ] **Asset Hosting paths** — Version → Asset Hosting: Panel Viewer Path `panel.html`, Config
      Path `config.html`, Live Config Path `live_config.html`. No leading `/` and no folder prefix
      such as `twitch-extension/` — a wrong path makes Twitch's CDN return 404 for the iframe
- [ ] **URL Fetching allowlist** — Version → Capabilities → Allowlist for URL Fetching Domains:
      `https://kana-cards.com`. No other entry is needed. Without it, Twitch's Content Security
      Policy blocks every EBS call
- [ ] **Backend setting** — set `TWITCH_EXTENSION_VERSION=1.2.0` on the EBS host once this
      version is installed on the channel, and confirm **Chat** is enabled for it. Without it the
      MVP chat announcement is skipped
- [ ] **Hosted Test verification** — move the version to **Hosted Test**, then load the panel,
      config and live config views on the review channel with browser dev tools open. Confirm no
      404, no CSP `connect-src` violation, and that the panel opens on the Live tab (never a
      login prompt and never "not configured")
- [ ] Submit

---

## Listing copy

**Name:** Kanaliiga Kana-Cards

**Summary** (one line):
> Live Kanaliiga fantasy results on stream, and a card game you play right in the panel with your
> Twitch login.

**Description** (full):
> Kana Cards brings the Kanaliiga Dota 2 fantasy league into the stream.
>
> **For every viewer:** the panel shows the latest match MVPs, the top fantasy performers of the
> latest games and the next scheduled match. No account is needed.
>
> **Play on Twitch:** viewers logged in to Twitch press **Join Kana Cards** to start. Join uses
> only the Twitch login: there is no sign-up, email or password. Players draw player cards, build
> a collection and set a weekly roster that scores from real league matches, all inside the
> panel. Tokens for draws come from a weekly grant and from MVP drops — no purchase or payment
> involved. Players can leave at any time in the panel's Settings, which deletes their game data.
> Kana Cards never asks for your Twitch or website password inside Twitch.
>
> **For broadcasters:** MVP selection and token drops live in Stream Manager → Quick Actions.
> Open Stream Manager, find the Kana Cards tile in the Quick Actions bar, and use it during or
> after a match to name the MVP and trigger a chat announcement plus a token drop to joined
> viewers currently watching.
>
> **Twitch Chat:** when the broadcaster confirms a match MVP, the extension posts one message to
> the channel's chat, for example: "Match MVP: PlayerName! 3 viewers received a token." It names
> the MVP and says how many viewers received a token; no viewer names are posted. If no eligible
> viewers (joined, with their Twitch identity shared) are watching, the message says no tokens were
> dropped. Changing the MVP for a match
> that already had a drop does not drop tokens again. The extension posts nothing else, and it
> never reads, stores or moderates chat messages.

This wording is deliberately consistent with `twitch-extension/config.html`'s broadcaster setup
copy and the panel's Settings privacy note — keep them in sync if any changes.

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
the viewer panel (Live tab, not joined; Cards tab with a card reveal; Roster tab) and the
broadcaster's live_config MVP-selection flow, not just the marketing/config page. `assets/logo_kanaliiga_primary.png` is available in this
repo as a possible source image if a fresh icon render is needed, though the extension's icon is
configured once in the dev console independent of code version and does not need to change for
this submission unless it's currently missing or undersized.

## Legal

Twitch's Extension Settings "Legal" tab requires a Privacy Policy URL (and typically Terms of
Service) since this Extension stores a Twitch id with game progress (soft accounts, issue #157). Both are published
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
| `/twitch/panel` | GET | `panel.js` | Live tab for every viewer: top performers of the latest games, next scheduled match |
| `/twitch/matches/current` | GET | `panel.js`, `live_config.js` | Recent series with MVPs (Live tab); MVP selection (broadcaster) |
| `/twitch/me` | GET | `panel.js` | The viewer's own game state: tokens, collection, roster, week points |
| `/twitch/join` | POST | `panel.js` | Creates the viewer's game account from the Twitch login (no sign-up) |
| `/twitch/draw` | POST | `panel.js` | Draw one card |
| `/twitch/teams` | GET | `panel.js` | Team draw picker: teams and players left to collect |
| `/twitch/draw/booster/{team_id}` | POST | `panel.js` | Team draw |
| `/twitch/roster/activate/{card_id}`, `/twitch/roster/deactivate/{card_id}`, `/twitch/roster/swap` | POST | `panel.js` | Roster changes |
| `/twitch/leave` | POST | `panel.js` | Leave: deletes the viewer's game data |
| `/twitch/heartbeat` | POST | `extension.js` (`startHeartbeat`) | Keeps a joined viewer in the token-drop pool (~every 55s while the panel is open) |
| `/twitch/mvp` | POST | `live_config.js` | Broadcaster-only: sets a match's MVP, triggers the token drop and chat announcement |

The panel no longer calls `/twitch/status` or `/twitch/link` (the link-code step was removed in
1.2.0). Since #160, `POST /twitch/link-code`, `POST /twitch/link` and `GET /twitch/status` are
removed from the backend (404); Twitch sign-in on the website replaces the code.

## Chat capability disclosure

The Extension uses Twitch's Extension Chat capability to post one message when a broadcaster
confirms a match MVP, e.g.:

> `Match MVP: PlayerName! 3 viewers received a token.`

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

The Extension's real functionality only has something to show when at least one match with
ingested player stats exists. Per Twitch's requirement that *"all submitted review channels must
be live during the time of review"*:

- Schedule the review during an active match week where `GET /twitch/matches/current` returns at
  least one series — an idle/off-season review will show empty states throughout
- Make sure the review channel is actually live at review time
- If `TWITCH_MVP_CHANNEL_IDS` is set on the server, add the review channel's ID to it before
  the review, or Flow 3 (MVP selection) fails with 403
- No website test account is needed: the reviewer joins with their own Twitch login

**Notes for reviewer (paste with the EBS block):**

> The panel works without an account: the Live tab shows MVPs, top performers and the next match
> to every viewer. Join uses only the Twitch login (plus Twitch's own identity-share dialog, which
> the viewer may decline). There is no link to, mention of, or login on any external website.
> Cards, the collection and the weekly roster are all played inside the panel.

## Steps to reproduce (paste into "Testing Instructions")

**Flow 1 — Viewer, logged out of Twitch**
1. Open the review channel logged out and expand the Kana Cards panel.
   **Expected:** the Live tab shows the latest MVPs, top performers and the next match, and the
   join box reads "Log in to Twitch to join".

**Flow 2 — Viewer, logged in: join and play**
1. Log in to Twitch, open the panel and press **Join Kana Cards**. Twitch shows its
   identity-share dialog; either answer works.
   **Expected:** the token count appears in the panel header.
2. Cards tab → **Draw · 1**. **Expected:** the drawn card is shown and added to the collection.
3. Cards tab → **Team draw · 3** → pick a team → **Draw from {team} · 3**.
4. Roster tab → **Change** or **+ Add a card** on a slot → pick a bench card.
   **Expected:** the roster shows the new card and a confirmation line.
5. Leave the panel open (a heartbeat keeps the viewer in the token-drop pool).

**Flow 3 — Broadcaster: select MVP, trigger token drop and chat announcement**
1. As the broadcaster, go to the Twitch Creator Dashboard → **Stream Manager**.
2. In the **Quick Actions** bar at the bottom, click the **Kana Cards** tile.
3. Click **Select match MVP**, select a series, a match and the MVP, then **Confirm MVP & Drop
   Tokens**.
   **Expected, all at once:**
   - The channel's chat receives: `Match MVP: <PlayerName>! N viewers received a token.`
   - The joined viewer from Flow 2 sees "+1 token from the MVP drop" in the panel
4. Optional: re-confirm the same match with a different player.
   **Expected:** the MVP name updates, but tokens are **not** dropped a second time.

**Flow 4 — Leave**
1. As the viewer, open Settings (gear icon) → **Leave Kana Cards** → press again to confirm.
   **Expected:** the panel returns to the not-joined Live tab.

## Security fix made for this submission

`live_config.js` (broadcaster MVP selection) built HTML by string-concatenating team and player
names directly into `innerHTML`. Those names come from OpenDota/Steam data ingested verbatim
with no server-side sanitization (`backend/ingest.py`), so this was a real stored-XSS risk —
also a direct violation of Twitch's *"DOM injection security"* requirement (*"Data from AJAX
requests must be validated and processed before DOM insertion"*). Fixed by adding an `_escHtml()`
helper to `extension.js` (mirroring `frontend/app-globals.js`'s existing helper) and escaping
every untrusted name before it's concatenated into an HTML string, in `twitch-extension-1.1.5`
(and carried forward into `1.1.6`).

## Confirmed compliant, no change needed

- No Flash, no iframes, unminified human-readable JS, package well under the 1MB mobile load cap
- Twitch Extension Helper script is the first `<script>` in every real front-end HTML file
  (`panel.html`, `config.html`, `live_config.html`)
- No off-site links, website mentions or login prompts in the viewer files; `package.sh` refuses to
  build if `panel.html`, `panel.js`, `extension.js`, `extension.css` or any `video*` component file
  contains "kana-cards.com", "Log into", "Generate Twitch Code" or "Link your account", or a
  password field
- Identity: Join calls `Twitch.ext.actions.requestIdShare()` (Twitch's own consent dialog). A
  viewer who declines still plays with the opaque id only
- No user-submitted content is shown to other users anywhere in the Extension, so the
  user-generated-content moderation rules don't apply

---

## Review history

### 2026-09 — Pending Approval (version 1.1.5)

| Guideline | Reviewer finding | Fix (version 1.1.6) |
|---|---|---|
| 1.2 | Extension did not load; the reviewer saw a 404 | The zip layout, EBS routing, CORS and helper script were all verified fine. The fix is dev-console configuration: exact Asset Hosting paths, `https://kana-cards.com` in the URL Fetching allowlist, and Hosted Test verification before submitting (checklist above). `package.sh` now fails on any unpackaged local reference and prints these console settings |
| 4.2 | Chat capability enabled but not described in the listing | Added the **Twitch Chat** paragraph to the listing description, with matching copy in `config.html` and the panel's unlinked view |

Details: [Twitch Review Resubmission](twitch-review-resubmission.md).

### 2026-09 — Version 1.1.7 change log

| File | Change |
|---|---|
| `live_config.js` | Matches seen live but not yet ingested are listed and marked **Live** or **Stats pending**; their player tiles show the team name without points; the confirmation banner says the fantasy bonus is applied when the stats arrive; the empty-state copy no longer mentions the ingest cycle. All names still go through `_escHtml`. See [Early MVP Selection](early-mvp-selection.md) |

### 2026-10 — Policy 4.5 rejection (version 1.1.7)

Finding: *"Extensions cannot require viewers to login to external sites in order to use them."*
The panel opened on "Log into kana-cards.com → Profile → Generate Twitch Code", and linking was
its only viewer value.

| File | Change (version 1.2.0, issue #157) |
|---|---|
| `panel.html`, `panel.js` | Live / Cards / Roster tabs and Settings; Join with the Twitch login and identity share; draws, team draw picker, collection, slot-first roster; Leave. Link-code UI and all website text removed; heartbeat only for joined viewers |
| `extension.css` | Kanaliiga design system (Big Shoulders packaged under `fonts/`) |
| `config.html`, `live_config.*` | Chat and drop copy reports a winner count, no viewer names |
| `live_config.html`, `live_config.js` | From #161: a freshness line above the MVP series list ("Live games checked N s ago", or an amber warning when the live check is stale or off) and a **Refresh** button that reloads the list. See [MVP Selection Delays](mvp-selection-delays.md) |
| `package.sh` | Forbidden-text and password-field self-check over the viewer files; packages the font |

Details: [Twitch Extension Policy Compliance](twitch-extension-policy-compliance.md).
