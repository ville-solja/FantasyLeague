# Twitch Extension Review Submission

Complete submission package for the Kanaliiga Kana-Cards Twitch Extension: ready-to-use listing
copy, required disclosures, and a step-by-step checklist covering every section of Twitch's
"Submit for Review" form, the dev-console Asset Hosting and URL Fetching settings the Extension
needs to load for a reviewer, plus the fixes made to satisfy
[Extension Guidelines & Policies](https://dev.twitch.tv/docs/extensions/guidelines-and-policies/)
in the process. See [Review history](#review-history) for past rejections.

**Package to submit:** `twitch-extension-1.3.0.zip`, built with
`bash twitch-extension/package.sh 1.3.0 --ebs-origin https://kana-cards.com` (since issue #164 the
package must name the backend origins the panel may call). Version `1.1.5` was the first with the XSS fix below;
`1.1.6` adds the chat disclosure copy required by the 2026-09 review; `1.1.7` adds the Live /
Stats pending labels for early MVP selection (issue #139) and was rejected under policy 4.5;
`1.2.0` makes the panel a complete game on Twitch with no website login (issue #157). `1.2.0` and
`1.2.1` were used in the console for testing only and are not submitted. `1.3.0` is the version
for review: the 1.2 game plus everything since (see the
[1.3.0 change log](#2026-10--version-130-change-log)). Twitch requires a new version for every
resubmission.

---

## Submission checklist (work through in order)

- [ ] **Production deploy** — run `bash scripts/backup-db.sh`, then deploy the current `main` to
      production. Migration 038 runs at the first start-up after the deploy, which logs
      `Migration applied: 038_twitch_starter_grants_backfill` once. If production already ran it,
      check the `schema_migrations` table instead: `SELECT applied_at FROM schema_migrations WHERE
      id = '038_twitch_starter_grants_backfill'` returns one row
- [ ] **Production env vars** — `TWITCH_EXTENSION_CLIENT_ID`, `TWITCH_EXTENSION_SECRET` (the
      Extension Secrets **Key**) and `TWITCH_EXTENSION_VERSION=1.3.0`. Without the version
      setting the MVP chat announcement is skipped
- [ ] **Drop age for the review window** — set `TWITCH_DROP_MIN_ACCOUNT_AGE_HOURS=0` on production
      and restart the backend, so the reviewer's new account is in the MVP drop (default 24 hours
      after joining). Set it back after the review (last step)
- [ ] **Extension Settings** — Configure method: **Extension Configuration Service** (click
      Save); **Developer Writable Channel Segment Version** left empty. A value there gates the
      extension per channel
- [ ] **Version** — build `bash twitch-extension/package.sh 1.3.0 --ebs-origin https://kana-cards.com`,
      create version `1.3.0` in the dev console and upload `twitch-extension-1.3.0.zip`
- [ ] **Backend URL (`ebs_url`)** — the global configuration's `ebs_url` is
      `https://kana-cards.com`. It is set once, and stays across versions; if it is missing or
      wrong, run `bash twitch-extension/set-ebs-url.sh https://kana-cards.com` (the extension must
      be in Local Test or higher). Admin › Twitch › Twitch status shows the expected value
- [ ] **Asset Hosting paths and Panel Height 500** — Version → Asset Hosting: Panel Viewer Path
      `panel.html`, Config Path `config.html`, Live Config Path `live_config.html`, Panel Height
      **500**. No leading `/` and no folder prefix such as `twitch-extension/`: a wrong path
      makes Twitch's CDN return 404 for the iframe
- [ ] **Allowlist for URL Fetching Domains** — Version → Capabilities: `https://kana-cards.com`.
      No other entry is needed. Without it, Twitch's Content Security Policy blocks every EBS call
- [ ] **Allowlist for Image Domains** — Version → Capabilities: each team logo host as
      `https://<host>`. With the default `LOGO_HOST_ALLOWLIST` these are
      `https://steamcdn-a.akamaihd.net`, `https://steamusercontent-a.akamaihd.net`,
      `https://cdn.steamusercontent.com`, `https://cdn.cloudflare.steamstatic.com` and
      `https://shared.cloudflare.steamstatic.com` (`backend/logo_hosts.py` `DEFAULT_LOGO_HOSTS`);
      Admin › Twitch › Twitch status lists the exact values. Without them the team draw shows a
      monogram (the first two letters of the team name) instead of each logo
- [ ] **Capabilities** — Version → Capabilities: **Chat** and **Request Identity Link** enabled
      (the configure method stays **Extension Configuration Service**, set under Extension
      Settings above). Chat use is disclosed in the **Twitch Chat** paragraph of the listing
      description (below); Join asks for Twitch's identity share
- [ ] **Approve the review channel** — open the MVP tool once on the review channel, then approve
      it under Admin › Twitch › **Approved streamers** (or add its ID to `TWITCH_MVP_CHANNEL_IDS`)
- [ ] **Connection check** — on the review channel, open the extension's configuration page:
      every row of the Connection check shows OK (Flow 5 below)
- [ ] **Hosted Test** — move the version to **Hosted Test**, then load the panel, config and live
      config views on the review channel with browser dev tools open. Confirm no 404, no CSP
      violation, and that the panel opens on the Live tab (never a login prompt and never "not
      available"). Walk Flows 1–5 below
- [ ] **Go/no-go** — Admin › Twitch › Twitch status on production shows every check green, or a
      warning only where it is explained: Connect Twitch (`TWITCH_OAUTH_*`) is a website feature
      the extension doesn't use, and without `STEAM_API_KEY` the MVP tool lists a match only once
      its stats arrive. No check may show a problem. Do not submit until then
- [ ] **Submission form** — listing copy (name, summary, description), category, icon and
      screenshots, Privacy Policy and Terms of Service URLs, support contact; **Notes for
      reviewer**: the EBS block, the Notes for reviewer block and the Changes since the last
      review block (below), verbatim; **Testing instructions**: Flows 1–5 below; the review
      channel is live during the review window (Reviewer test setup)
- [ ] Submit
- [ ] **After the review** — set `TWITCH_DROP_MIN_ACCOUNT_AGE_HOURS` back to `24` (or remove it)
      and restart the backend

Capability fields (URL Fetching Domains, Image Domains, Chat, Request Identity Link) are editable
only while the version is in **Local Test**. Set them before moving to Hosted Test; to change them
later, move the version back to Local Test. The console field names match the Prerequisites table
in [Twitch Extension](../core/twitch-extension.md#prerequisites--developer-console-settings).

---

## Listing copy

**Name:** Kanaliiga Kana-Cards

**Summary** (one line):
> Live Kanaliiga fantasy results on stream, and a card game you play right in the panel with your
> Twitch login.

Twitch caps the Description field at 1,024 characters, so the chat paragraph comes first and the whole text stays under 1,000 (`test_listing_description_fits_1024_characters`). Paste it as plain text, without the `**` markers.

**Description** (full):
> **Twitch Chat:** when the broadcaster confirms a match MVP, the extension posts one message in chat, one of: "Match MVP: PlayerName! 3 viewers received a token." / "Match MVP: PlayerName! No tokens were dropped: no joined viewers were watching." / "Match MVP: PlayerName! No tokens were dropped: new accounts join drops 24 hours after joining." / "Match MVP: PlayerName!" (after an MVP change, which does not drop tokens again, or with token drops off). No viewer names are posted. It posts nothing else and never reads, stores or moderates chat.
>
> Joining gives starter tokens; players win more tokens when the broadcaster picks a match MVP: the MVP drop gives one token each to up to 20 joined viewers who have the panel open, picked at random, and new players are included after a waiting period (no purchase or payment involved). Players can leave at any time in the panel's Settings, which deletes their game data. Kana Cards never asks for your password inside Twitch.

The earlier description was about 2,370 characters with the chat paragraph at the end, starting around character 1,330. The 2026-10 review again reported 4.2 ("description does not contain information on what your Extension actually does with that functionality"), most likely because the field cut the text before the chat paragraph. The broadcaster how-to (Stream Manager → Quick Actions) moved to the reviewer test flows below.

This wording is deliberately consistent with `twitch-extension/config.html`'s broadcaster setup
copy ("win tokens from MVP drops"), the panel's join view ("win tokens when the broadcaster picks a
match MVP") and its Settings privacy note — keep them in sync if any changes. The panel's draw note
("Tokens come from MVP drops and the weekly grant.") names the same weekly token: when a match week
locks, every account gets +1 (`backend/weeks.py` `auto_lock_weeks`).

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

Screenshots must **accurately represent current functionality** per Twitch's guidelines. The
panel looks different from 1.1.7, so retake these for 1.3.0 (at Panel Height 500):

1. The panel's **Live tab, not joined** (the Join box above Latest MVPs, Top performers, Next match)
2. The **Cards tab with a reveal** after **Draw · 1**
3. The **Roster** tab with filled slots
4. **Settings with Leave** (the identity share box and **Leave Kana Cards**)
5. The broadcaster's **MVP selection** in Stream Manager → Quick Actions (live_config)

Not just the marketing/config page. `assets/logo_kanaliiga_primary.png` is available in this
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

**support@kana-cards.com** — enter exactly this in the submission form's support contact field. The same address
is written into the Testing Instructions (Steps to reproduce below and the walkthrough block in
`markdown/plans/plan-issue-195-twitch-extension-resubmission.md`), so the reviewer and viewers get
one contact everywhere. Use the email, not a website link: the listing and reviewer notes say no
external website is needed.

---

## EBS URL disclosure (required — paste into "Notes for reviewer")

Twitch's guidelines require **all externally-fetched URLs to be disclosed with the
submission**. The panel's backend origins are fixed in the package when it is built:
`package.sh --ebs-origin` writes them into the packaged `ebs-origins.js` (`EBS_ALLOWED_ORIGINS`,
issue #164). `twitch-extension/extension.js` reads the backend URL (`ebs_url`) at runtime from the
Twitch Extension Configuration Service (`Twitch.ext.configuration.global`) and uses it only when it
is `https:` and its origin is one of the packaged origins. **Paste this into the submission's
"Notes for reviewer" field:**

> The Extension's backend (EBS) origins are fixed in this package at build time, in
> `ebs-origins.js` (`EBS_ALLOWED_ORIGINS`). This package allows only **`https://kana-cards.com`**.
> The backend URL itself is read at runtime from the Extension Configuration Service's global
> config segment (`ebs_url` key), and the Extension uses it only when its origin is one of the
> packaged origins; otherwise it shows a short error code and makes no backend call. All Extension
> frontend network calls go to this single host, at the paths listed below.
>
> Images: the panel's team draw shows team logos loaded directly from Steam's image CDN
> (`steamcdn-a.akamaihd.net`, `steamusercontent-a.akamaihd.net`, `cdn.steamusercontent.com`,
> `cdn.cloudflare.steamstatic.com`, `shared.cloudflare.steamstatic.com`), and only from `https://`
> URLs; otherwise it shows a monogram (the first two letters of the team name). No other external domain is contacted from the
> Extension's own frontend code (the Twitch Extension Helper script itself is loaded from Twitch's
> own `extension-files.twitch.tv` CDN, per Twitch's required inclusion). Fonts are packaged.
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
| `/twitch/ping` | GET | `config.js` | Configuration page, Connection check: is the backend reachable (no Twitch token sent) |
| `/twitch/check` | GET | `config.js` | Configuration page, Connection check: is the Twitch token accepted, and is the channel approved to set MVPs |

The panel no longer calls `/twitch/status` or `/twitch/link` (the link-code step was removed in
1.2.0). Since #160, `POST /twitch/link-code`, `POST /twitch/link` and `GET /twitch/status` are
removed from the backend (404); Twitch sign-in on the website replaces the code.
`backend/tests/test_issue_195_twitch_extension_resubmission.py` compares this table with the paths
in the packaged JS in both directions, and checks each path against the backend routes.

## Chat capability disclosure

The Extension uses Twitch's Extension Chat capability to post one message when a broadcaster
confirms a match MVP. The message is built by `_mvp_chat_text` in `backend/twitch.py` and is always
one of these four (the listing's **Twitch Chat** paragraph lists the same four, and
`backend/tests/test_twitch_review_resubmission.py` checks them against the code):

| Case | Exact message |
|---|---|
| Tokens dropped to N joined viewers | `Match MVP: PlayerName! 3 viewers received a token.` (`1 viewer received a token.` for one) |
| No joined viewer has the panel open | `Match MVP: PlayerName! No tokens were dropped: no joined viewers were watching.` |
| Only accounts newer than the drop age are watching | `Match MVP: PlayerName! No tokens were dropped: new accounts join drops 24 hours after joining.` (the hours follow `TWITCH_DROP_MIN_ACCOUNT_AGE_HOURS`, default 24; if it changes, change the listing too) |
| MVP changed on a match that already dropped, or drops switched off | `Match MVP: PlayerName!` |

`PlayerName` is the league player's name, cleaned by `chat_safe_name` (no control or bidi
characters, at most 32 characters, `Player <id>` when the name looks like a link). The text is
capped at 280 characters. No viewer names or usernames are ever posted. No other chat activity is
read, stored, or posted. This does not use Twitch Bits — "tokens" here
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

- **Live channel and active match week:** schedule the review during an active match week where
  `GET /twitch/matches/current` returns at least one series (an idle/off-season review shows
  empty states throughout), and make sure the review channel is actually live at review time
- **Approved review channel:** approve the review channel before the review, or Flow 3 (MVP
  selection) shows "This channel is waiting for the league's approval to set match MVPs." and
  `POST /twitch/mvp` returns 403: open the MVP tool once on the review channel, then approve it
  under Admin › Twitch › **Approved streamers** (issue #175), or add its ID to
  `TWITCH_MVP_CHANNEL_IDS`. In production one of the two is required (issue #165)
- **Version and Chat:** `TWITCH_EXTENSION_VERSION=1.3.0` on the EBS host, and **Chat** enabled
  for version 1.3.0 in the console. Without either, the MVP chat announcement is skipped
- **Drop age:** a new account joins MVP drops `TWITCH_DROP_MIN_ACCOUNT_AGE_HOURS` (default 24)
  after joining (issue #171), so with the default the reviewer's fresh account gets no token in
  Flow 3: its Live tab shows "Drops start for your account on …". The checklist sets it to `0`
  for the review window and back afterwards
- No website test account is needed: the reviewer joins with their own Twitch login

**Notes for reviewer (paste with the EBS block):**

> The panel works without an account: the Live tab shows MVPs, top performers and the next match
> to every viewer. Join uses only the Twitch login (plus Twitch's own identity-share dialog, which
> the viewer may decline). There is no link to, mention of, or login on any external website.
> Cards, the collection and the weekly roster are all played inside the panel.

### Changes since the last review (paste into "Notes for reviewer")

> Changes since the last review (version 1.2.1, policy 4.2):
> - Policy 4.2: the listing description now starts with the Twitch Chat paragraph, which quotes
>   each of the four messages the extension can post when the broadcaster confirms a match MVP, and
>   says it posts nothing else and never reads, stores or moderates chat. Flow 2 of the Testing
>   Instructions shows the messages.
> - The panel takes the height set in the version's Panel Height, and each view scrolls inside it
>   with a thin visible scrollbar. In the roster card picker, the current slot box stays visible
>   while the list scrolls.
> - The build reads 1.3.0 in the configuration page's Connection check.
> - No change to chat behaviour, data collected, backend calls or capabilities.
> As in 1.2.1, the extension no longer requires or mentions any external login: everything is
> played in the panel with the Twitch login, and Twitch's identity share is optional (declining it
> changes nothing in the game).

## Steps to reproduce (paste into "Testing Instructions")

The review channel is live during a Kanaliiga match week. Easiest with two Twitch accounts in two
browsers (or a normal and a private window): the review channel's broadcaster, and any other account
as the viewer. One account also works: the broadcaster can join in the panel and then counts as a
viewer. The panel is 318 px wide and up to 500 px tall; each tab scrolls within that height. If a
section can't load, its message ends with a short code such as `(code: E-REACH)`: please include
the code in your feedback, or send it to support@kana-cards.com.

**Flow 1 — Viewer: Live tab and Join**
1. While logged out of Twitch, open the review channel and the Kana Cards panel.
   **Expected:** the Live tab shows "Latest MVPs", "Top performers" and "Next match", and the join
   box reads "Log in to Twitch to join. The Live tab is open to everyone."
2. In the viewer browser, log in, open the panel and press **Join Kana Cards**. Twitch shows its
   identity-share dialog; either answer works.
   **Expected:** "You joined Kana Cards with <N> tokens." and the token count in the panel header.
3. Keep this panel open. Only joined viewers with the panel open (seen in the last 10 minutes) are
   in the MVP token drop.

**Flow 2 — Broadcaster: MVP, token drop and the chat message (Chat capability)**
This is everything the extension does with Twitch Chat. Each confirmation posts exactly one
message, always one of the four quoted in the listing description; it posts nothing else and never
reads, stores or moderates chat.
1. In the broadcaster browser: Creator Dashboard → **Stream Manager** → the **Kana Cards** tile in
   the **Quick Actions** bar.
2. Click **Select match MVP**, then pick a series, a match and a player. The tool previews the start
   of the message, `Chat will say: "Match MVP: <PlayerName>!"`; the token part is added after the
   drop.
3. Click **Confirm MVP & Drop Tokens**.
   **Expected:** chat shows `Match MVP: <PlayerName>! N viewers received a token.` (`1 viewer` for
   one), where N is the number of joined viewers with the panel open, including the broadcaster if
   they joined. No viewer names are posted. Within a few seconds the viewer's panel shows
   "+1 token from the MVP drop".
4. Confirm the same match again with a different player.
   **Expected:** chat shows `Match MVP: <OtherPlayer>!` and no token is dropped again.
5. Optional: close the viewer's panel, wait 10 minutes, and confirm the MVP of a different match
   that has no MVP yet.
   **Expected:** chat shows `Match MVP: <PlayerName>! No tokens were dropped: no joined viewers were watching.`
The fourth message (new accounts waiting 24 hours) is switched off for the review window. If the
tool says "No recent matches found. A match appears here as soon as it goes live.", no match is in
progress: please contact support@kana-cards.com for a time when one is live.

**Flow 3 — Viewer: cards and roster**
1. Cards tab → **Draw · 1**. **Expected:** the card is revealed with "Added to your roster" or
   "Added to your bench".
2. Cards tab → **Team draw · 3** → pick a team → **Draw from <team> · 3**. **Expected:** a card of
   that team is revealed (3 tokens).
3. Roster tab → **Change** or **+ Add a card** on a slot → pick a card. **Expected:** the roster
   shows it, with a line such as "<Player> in."

**Flow 4 — Viewer: leave**
1. Settings (gear icon) → **Leave Kana Cards** → "Press again to leave". **Expected:** "You left
   Kana Cards." and the panel returns to the not-joined Live tab.

**Flow 5 — Broadcaster: configuration page Connection check**
1. Creator Dashboard → Extensions → Kana Cards → Settings. **Expected:** the "Connection check"
   list shows "OK" for Package, Backend address, Backend reachable, Twitch token accepted and MVP
   selection; Package shows the version, 1.3.0. **Check again** reruns it.

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

### 2026-10 — Version 1.3.0 change log

Every packaged file changed between 1.1.7 (commit `4c34cef`) and 1.3.0. 1.2.0 and 1.2.1 were
test-only builds along the way.

| File | Change |
|---|---|
| `panel.html` | Live / Cards / Roster tabs, Settings, Join box, team draw and bench pickers, with no website text (#157); "Drops start for your account on …" line (#171); loads `ebs-origins.js` (#164); views sized to the panel height (#191) |
| `panel.js` | The panel game: Join with the Twitch login and optional identity share, draws, team draw, collection, slot-first roster, Leave; heartbeat for joined viewers only (#157); reason codes on "not available" messages (#180); team logos only from `https://` URLs; scroll position kept per tab (#191) |
| `config.html` | Copy describes the panel game and a chat message with a winner count, no website mention (#157); loads `ebs-origins.js` (#164); **Connection check** section (#180) |
| `config.js` | New: the Connection check (Package, Backend address, Backend reachable via `/twitch/ping`, Twitch token accepted and MVP selection via `/twitch/check`) with its reason code (#180) |
| `live_config.html` | Loads `ebs-origins.js` (#164); live-games freshness line and **Refresh** button (#161), chat preview line (#166), "not available" note (#180) |
| `live_config.js` | Freshness and Refresh (#161), approval message for channels not yet approved (#175), chat preview (#166), drop result as a winner count with no names (#157), reason codes (#180) |
| `extension.js` | Calls the configured backend URL only when its origin is packaged (#164); reason codes `E-ORIGIN`, `E-CONFIG`, `E-REACH`, `E-TOKEN`, `E-SERVER` (#180) |
| `ebs-origins.js` | New: the packaged backend origins (#164) and build stamp (#180), written by `package.sh` |
| `extension.css` | Kanaliiga design system for the new panel (#157); views scroll within the panel height, thin themed scrollbars (#191) |
| `fonts/BigShouldersText-VariableFont_wght.ttf` | New: the packaged Big Shoulders Text font (#157) |
| `fonts/BigShouldersText-OFL.txt` | New: the font's licence (#157) |

`package.sh` (not packaged) gained the forbidden-text and password-field check, packaging of the
font, the required `--ebs-origin`, the version-format check, the build stamp, and the Panel Height
and Image Domains reminders.

Details: [Twitch Extension Resubmission](twitch-extension-resubmission.md).

### 2026-10 — Pending Approval again on 4.2 (version 1.2.1)

Finding: *"Your Extension has the "Chat Capabilities" capability enabled … but your description
does not contain information on what your Extension actually does with that functionality."*

The description did have a **Twitch Chat** paragraph, but at the end of a text of about 2,370
characters, starting around character 1,330. Twitch's Description field holds 1,024 characters, so
the paragraph was most likely cut off before the reviewer saw it.

| Change | Where |
|---|---|
| The description is under 1,000 characters and opens with the Twitch Chat paragraph | [Listing copy](#listing-copy) |
| The paragraph quotes each message the extension can post | [Chat capability disclosure](#chat-capability-disclosure) |
| Tests keep the description within the limit, the chat paragraph first, and every message the code can post quoted | `backend/tests/test_twitch_review_resubmission.py` |
| The "Changes since the last review" block names the 4.2 fix | [Changes since the last review](#changes-since-the-last-review-paste-into-notes-for-reviewer) |

To be resubmitted as version 1.3.0 (`bash twitch-extension/package.sh 1.3.0 --ebs-origin https://kana-cards.com`,
built 2026-10-26) with the new description pasted, Chat enabled on 1.3.0, and
`TWITCH_EXTENSION_VERSION=1.3.0` on the EBS host. Open items and the paste-ready walkthrough:
`markdown/plans/plan-issue-195-twitch-extension-resubmission.md`. Record the submission date and
outcome here once known.
