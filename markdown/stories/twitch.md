# Twitch Integration

### MVP Selection and Token Drop
**User story**
As a broadcaster, I want to select the MVP of a completed match from the Quick Actions panel so that tokens are automatically dropped to viewers who are watching.

**Acceptance criteria**
- Broadcaster opens Quick Actions (Live Config view in Twitch Stream Manager) and clicks "Select match MVP"
- Flow: select series (team1 vs team2) → select match (Match 1, Match 2…) → select player from the match roster
- Confirming MVP saves the selection and fires a one-time token drop to the presence pool
- Drop fires only on the **first** confirmation for a given match — re-confirming a different player for the same match does not re-drop
- Up to `TWITCH_DROP_MAX` (default 20) randomly selected joined viewers (soft accounts or website accounts (code-linked before #160, or connected with Twitch sign-in), #157) from the pool receive +1 token
- Broadcaster sees confirmation: MVP player name + count of viewers who received tokens

---

### Viewer Panel
*Superseded by [Policy 4.5 Compliance (Part 1, #157)](#policy-45-compliance-part-1-157): the panel opens on a Live tab, viewers join with their Twitch login, and the link-code step is gone.*

**User story**
As a viewer, I want to open the Twitch panel during a Kanaliiga stream so I can see my token balance, the current MVP, and be eligible for token drops.

**Acceptance criteria**
- Panel fetches the EBS URL from `Twitch.ext.configuration.global.content` at startup — no viewer-side or broadcaster-side URL configuration needed
- Unlinked viewers see the account linking instructions (enter 6-char code from the Fantasy Profile tab)
- Linked viewers see their token balance and linked username
- MVP announcements arrive via PubSub and display as a temporary banner
- Token drop winner announcements also display via PubSub and refresh the token count
- If the EBS URL is missing or unreachable, the panel shows a clear error rather than a blank state

---

### Account Linking
*Superseded by #157 and #160: the extension no longer has a code field, Profile no longer offers "Generate Twitch Code", and #160 (done) replaced the link code with Twitch sign-in on the website (Profile › Connect Twitch); the link-code routes are removed. Accounts linked by code earlier keep working in the panel.*

**User story**
As a Fantasy League user, I want to link my Twitch account so I am eligible for token drops while watching the stream.

**Acceptance criteria**
- User navigates to the Fantasy Profile tab and clicks "Generate Twitch Code"
- A 6-character alphanumeric code is displayed with a 10-minute countdown
- User enters the code in the Twitch extension panel and clicks Link
- Backend validates the code, stores the Twitch opaque user ID on the user record, and confirms the link
- Once linked, the panel shows token balance and the user is eligible for future drops

---

### Broadcaster Extension Installation
**User story**
As a broadcaster for Kanaliiga, I want to install the Twitch extension and start using it immediately — without manually configuring any backend URLs.

**Acceptance criteria**
- Extension works immediately after install — EBS URL is pre-configured globally by the Kanaliiga developer, no per-channel action required
- Quick Actions (Live Config view) are visible in the Twitch Stream Manager dashboard after install

---

### Operator EBS URL Configuration
**User story**
As the Kanaliiga developer, I want to set the EBS URL once in the Twitch developer console so that all channel installs of the extension automatically point to the correct backend.

**Acceptance criteria**
- Required developer console settings are documented with a prerequisite checklist
- Running `bash twitch-extension/set-ebs-url.sh <url>` sets the global Configuration Service segment
- The extension reads `Twitch.ext.configuration.global.content` at startup — URL change takes effect immediately on next panel load
- `.env` requires only `TWITCH_EXTENSION_CLIENT_ID`, `TWITCH_EXTENSION_SECRET`, and `TWITCH_DROP_MAX`

---

### MVP Fantasy Score Bonus
**User story**
As a fantasy league player, I want the designated MVP of a match to earn an extra percentage on their fantasy score for that match so that the broadcast MVP appointment has real in-game value.

**Acceptance criteria**
- When a broadcaster confirms an MVP via the Twitch extension, that player's `fantasy_points` for that specific match is multiplied by `(1 + mvp_bonus_pct / 100)`
- If the broadcaster later changes the MVP to a different player for the same match, the old player's bonus is removed and the new player receives it
- The bonus is reflected immediately in roster point totals, leaderboard standings, and the player match history
- An MVP match is visually distinguishable from a regular match in the player detail modal

---

### Configurable MVP Bonus Weight
**User story**
As an admin, I want to configure the MVP fantasy bonus percentage from the admin weights panel so I can tune its value without code changes.

**Acceptance criteria**
- A weight key `mvp_bonus_pct` (label: "MVP bonus (%)") is present in the admin weights panel with a default of `10.0`
- Changing the value and running `POST /recalculate` re-applies the updated bonus to all MVP-flagged matches
- `mvp_bonus_pct = 0` effectively disables the bonus without removing the MVP flag from past matches

---

## MVP Series Window and Live Polling

### MVP Panel Shows 5 Most Recent Series with Ingested Data
**User story**
As a broadcaster, I want the MVP selection panel to always show the 5 most recent series
that have completed match data so I can appoint MVP even when no matches have been ingested
for the current week or the series spans a week boundary.

**Acceptance criteria**
- `GET /twitch/matches/current` returns the 5 most recent series (by latest match `start_time`) that have at least one match with ingested player stats
- Series are not limited to the current or any single week
- Series are sorted most-recently-played first
- If fewer than 5 qualifying series exist, all available are returned
- Matches within each series are still limited to those that have already started (`start_time ≤ now`)
- The extension panel shows correct match and player data regardless of week boundary

---

### Faster Ingest Polling During Active Weeks
**User story**
As a broadcaster, I want match data to appear in the MVP panel within a few minutes of a
match ending so I can appoint MVP promptly after the game concludes.

**Acceptance criteria**
- A new `INGEST_LIVE_POLL_INTERVAL` env var (default: `120`) controls the polling interval used when an active (unlocked, currently-running) week exists
- When no active week is in progress, the existing `INGEST_POLL_INTERVAL` (default: 900) is used instead
- `.env.example` documents `INGEST_LIVE_POLL_INTERVAL` with a description

---

## Extension Review Resubmission

### Reviewer Can Load Every Extension View
**User story**
As a Twitch Extension reviewer, I want every view of the Extension to load from Twitch's hosted CDN so that I can complete a full functional review.

**Acceptance criteria**
- The dev console's Asset Hosting paths are exactly `panel.html` (Panel Viewer Path), `config.html` (Config Path) and `live_config.html` (Live Config Path), with no leading slash or folder prefix
- The submitted version is uploaded and moved to **Hosted Test** before submission, and all three views load in Hosted Test without a 404 on a real channel
- The panel view reaches either the unlinked or linked state, never the "not configured" error, when loaded in Hosted Test
- The submitted zip version is higher than `1.1.5`

---

### EBS Domain Allowlisted for Fetch
**User story**
As the Kanaliiga developer, I want the backend domain allowlisted in the dev console so that Twitch's Content Security Policy does not block the Extension's API calls.

**Acceptance criteria**
- The console's **Allowlist for URL Fetching Domains** contains `https://kana-cards.com`
- No other external domain is fetched by the Extension frontend, so no other entry is needed
- In Hosted Test, the browser console shows no CSP `connect-src` violation when the panel calls `/twitch/me`
- The submission checklist lists the allowlist step before "Submit"

---

### Package Self-Check Before Upload
**User story**
As the Kanaliiga developer, I want the packaging script to fail when an HTML file references a local file missing from the zip so that a broken package never reaches review.

**Acceptance criteria**
- `bash twitch-extension/package.sh <version>` exits non-zero and names the missing file if any `src` or `href` in a packaged HTML file points to a local file not in the package
- The script exits non-zero if no version argument is given, instead of silently defaulting to `1.0.0`
- The script exits non-zero if the output zip already exists, instead of updating a previously submitted archive in place
- On success, the script prints the exact console Asset Hosting paths and the fetch allowlist entry to set
- A pytest test asserts every local asset referenced by `panel.html`, `config.html` and `live_config.html` is in the package file list, and that the Twitch helper script is the first `<script>` in each

---

### Chat Usage Disclosed in Listing
*Partly superseded by #157: the chat now names the MVP and only how many viewers received a token ("N viewers received a token"), never usernames; with no joined viewers it says no tokens were dropped. The panel's unlinked view is gone — the Join box carries the consent line instead, and `config.html` says no viewer names are posted. The criteria below are kept as originally written.*

**User story**
As a Twitch reviewer and as a viewer, I want the Extension description to explain what it posts in chat so that I know how it interacts with Twitch Chat.

**Acceptance criteria**
- The listing description has a dedicated chat paragraph. It says the Extension posts one message to the channel's chat when the broadcaster confirms a match MVP, and never at any other time
- The paragraph states the message contents: the MVP player's name, and the Kanaliiga Fantasy usernames of viewers who won the token drop, or a note that no linked viewers were in the pool
- The paragraph states the Extension does not read, store or moderate chat, and re-selecting the MVP for a match that already had a token drop does not drop tokens again
- `twitch-extension/config.html`'s broadcaster copy mentions the chat announcement, consistent with the listing description
- The panel's unlinked view tells viewers that linking can show their Kanaliiga username in chat if they win a drop

---

## Early MVP Selection

### Pick the MVP Right After the Game
**User story**
As a streamer, I want a match to appear in the MVP panel as soon as it starts so that I can confirm the MVP the moment the game ends, while viewers are still watching.

**Acceptance criteria**
- Each live check stores every live game of a monitored league in a `live_matches` table (since #161 the games come from Steam's `GetLiveLeagueGames`, checked by their own thread; previously OpenDota's `/live` in the ingest poll): match id, league id, both team ids and names, the ten players (account id, name if given, side), and first and last seen times
- `GET /twitch/matches/current` includes a stored live match that has no ingested stats yet, in the series of its team pair, within the existing 5-series window
- Such a match has `"provisional": true`, `"live": true` while it is still in the live list and `false` after, and a `players` list built from the stored players with `fantasy_points: 0`
- A match with ingested stats is listed exactly as today with `"provisional": false`, and is never listed twice
- A live match whose team ids are missing is still listed, grouped under its team names

### Confirm an MVP Before Stats Exist
**User story**
As a streamer, I want confirming an MVP on a provisional match to work like any other confirmation so that the chat message and token drop happen immediately.

**Acceptance criteria**
- `POST /twitch/mvp` accepts a provisional match id in the series window, when the player is one of that match's stored live players
- It stores the MVP row, runs the token drop, posts the chat message using the player's display name (known `players` name, else live `name`, else `Player {account_id}`), and writes the `twitch_mvp_set` audit entry with `provisional=True` in the detail
- No fantasy bonus is applied at confirm time, because there is no stats row yet
- A player not among the match's stored live players gets 404 "Player did not play in this match"
- The channel allowlist and series-window checks run first and behave as today
- Changing the MVP on a provisional match updates the row and does not drop tokens again

### Bonus Applied When Stats Arrive
**User story**
As a player owner, I want an MVP picked early to get the same fantasy bonus as one picked after ingest so that early selection changes nothing about scoring.

**Acceptance criteria**
- When the match is ingested, `_reapply_mvp_bonus` sets `is_mvp` and the bonus on the chosen player's stats row, as for any MVP
- If the chosen player has no stats row in the ingested match, a warning is logged naming the match and player, and nothing else changes
- Once a match has stats rows, its `live_matches` row is deleted
- A stored live match that has not been ingested 24 hours after it was last seen (for example because ingest skipped a game shorter than 15 minutes) is deleted and no longer listed. An MVP row already confirmed for it stays but has no effect

### Faster Ingest Right After a Game Ends
**User story**
As a streamer, I want the final stats to arrive soon after the game so that the panel shows real points shortly after I pick.

**Acceptance criteria**
- While any stored live match of a monitored league has ended but has no ingested stats, the poll loop keeps using `INGEST_LIVE_MATCH_POLL_INTERVAL`
- This faster polling stops after `INGEST_POST_MATCH_FAST_POLL_MINUTES` (default 20) from the end of the match, even if the match is still not ingested
- With no live or recently ended matches, intervals are unchanged

### Panel Shows Which Matches Are Provisional *(extension release)*
**User story**
As a streamer, I want the panel to show when a match is live or waiting for stats so that I know the points are not final.

**Acceptance criteria**
- A provisional match row shows "Live" while `live` is true, otherwise "Stats pending"
- Player tiles of a provisional match show the team name without a points value
- After confirming on a provisional match, the confirmation says the bonus is applied when the stats arrive
- The empty-state text no longer says to wait for the next ingest cycle
- `live_config.js` passes the extension package self-check (`twitch-extension/package.sh`) and is released as a new extension version

---

## Chat Announcement Fix

### MVP Announcement Reaches Chat
**User story**
As a streamer, I want the MVP and token-drop winners announced in my channel's chat so that viewers without the panel open see them too.

**Acceptance criteria**
- `_post_chat_message` sends `{"text", "extension_id", "extension_version"}`, with `extension_id` from `TWITCH_EXTENSION_CLIENT_ID` and `extension_version` from `TWITCH_EXTENSION_VERSION`
- The request keeps `broadcaster_id` as a query parameter and a JWT with `role: "external"`, `user_id` and `channel_id` equal to the broadcaster's channel
- When `TWITCH_EXTENSION_VERSION` is unset, no request is sent and a warning is logged once per process naming the missing setting
- Local dev (`TWITCH_LOCAL_DEV=true`) still logs the message instead of calling Twitch

### Announcements Fit Twitch's Limit
**User story**
As a streamer, I want a large token drop still announced so that a long winner list doesn't stop the message.

**Acceptance criteria**
- The announcement text is at most 280 characters for any realistic MVP name; the MVP name is never cut
- When the winners don't all fit, the message lists as many as fit, followed by "and N more"
- The MVP name is always included in full

### Failures Are Visible to Operators
**User story**
As an operator, I want failed Twitch calls logged with Twitch's reason so that the next problem can be diagnosed from the server log.

**Acceptance criteria**
- A chat or PubSub response other than 2xx logs a warning with the HTTP status and Twitch's error message (response body, truncated to 300 characters), and never the JWT
- A timeout or connection error is still logged, as today
- `POST /twitch/mvp` returns 200 and keeps the MVP, bonus and token drop when the chat or PubSub call fails

## Policy 4.5 Compliance (Part 1, #157)

### Live Fantasy for Every Viewer
**User story**
As a viewer watching a Kanaliiga stream, I want the panel to show live fantasy information without any account so that it's useful the moment I open it.

**Acceptance criteria**
- **Default view:** the panel opens on a **Live** tab for every viewer, logged in to Twitch or not. It shows:
  - the latest series MVPs (`GET /twitch/matches/current`, with "(live)" markers kept),
  - the top 3 fantasy performers of the latest games,
  - the next scheduled match.
- **Data source:** the new endpoint `GET /twitch/panel` (extension JWT, any role, including anonymous viewers) returns the top performers and the next match from the existing queries behind `GET /top` and `GET /schedule`. It doesn't run that logic twice, and returns public data only.
- **Refresh:** every 60 seconds while the panel is open, and immediately on an MVP announcement over PubSub.
- **No outside calls to action:** no extension file contains a login, link code, registration or kana-cards.com call-to-action. `twitch-extension/package.sh` refuses to build if a viewer file contains "kana-cards.com", "Log into", "Generate Twitch Code" or "Link your account".
- **Failure path:** when the EBS is unreachable or a section has no data, that section shows a short neutral message. It never shows a blank panel or a login prompt.

### Join Kana Cards on Twitch (Soft Account Creation)
**User story**
As a viewer logged in to Twitch, I want to join with one button so that I can start collecting cards without creating an account anywhere.

**Acceptance criteria**
- **Join button:** the Live tab shows **Join Kana Cards** to viewers who haven't joined, with the consent line "Uses your Twitch login. We store your Twitch id and game progress; leave any time in Settings." The Cards and Roster tabs show the same button until the viewer joins.
- **Logged out of Twitch:** with an `A…` opaque id, the button is replaced by "Log in to Twitch to join". `POST /twitch/join` returns 403 `twitch_login_required`. This is the failure path.
- **`POST /twitch/join`** (extension JWT, role viewer, broadcaster or moderator):
  - **Normal case:** creates one `users` row with:
    - `account_type="twitch"` and `twitch_user_id` set to the opaque id,
    - `username`, `email` and `password_hash` all NULL,
    - `tokens = INITIAL_TOKENS`, and `created_at` and `last_seen_at` set to now.
  - **Already joined:** if any user (soft or website) already has that `twitch_user_id`, it returns that account's state and creates nothing. Repeated presses are safe.
  - **Race-safe:** two simultaneous joins with the same id produce one account. The existing unique constraint on `users.twitch_user_id` plus catching the integrity error guarantees it.
  - **Rate limit:** per opaque id and per IP, using the existing slowapi limiter.
  - **Audit:** writes `twitch_soft_account_created` with the new user id. The opaque id isn't written to the audit detail.
- **Identity share:** pressing Join first calls `Twitch.ext.actions.requestIdShare()`.
  - When the viewer agrees, `POST /twitch/join` (and any later call carrying a JWT with `user_id`) stores that id in `twitch_account_id`. The column is unique, and an existing value is never overwritten with a different one.
  - When the viewer declines, Join still works, and panel Settings offers "Share your Twitch identity" later.
  - No other personal data is requested.
- **Website safety:** a soft account can never sign in on the website. It has no username or password, so `POST /login`, forgot-password and the username allowlist all reject it. No website endpoint can create a soft account.
- **`GET /twitch/me`** (extension JWT): returns `{joined: false}` for a viewer without an account. For a joined viewer it returns:
  - `joined`, `tokens`,
  - `collection`: owned cards with player, team, rarity and modifiers,
  - `roster`: from `_build_roster_response` for the editable week,
  - `week_points`: the current week so far.
  
  It never returns another user's data. `last_seen_at` is updated at most once an hour.

### Draw Cards and Set a Roster in the Panel
**User story**
As a player in the extension, I want to draw cards and set my weekly roster in the panel so that my tokens are useful on Twitch.

**Acceptance criteria**
- **Cards tab:**
  - **Draw · 1** calls `POST /twitch/draw`. It runs the same logic as the website (`draw_card`): token cost, the rarity roll, modifiers, "unowned players first", and adding the card to the roster when there's room.
  - **Team draw · 3** opens a **team picker** inside the panel, as on the website's team draw:
    - a "Team draw" heading with **Back** and the line "Pick a team. You get one of its players you don't own yet. Costs 3 tokens.",
    - a **two-column list of compact team rows** (44 px tall) for all the season's teams, 14 now. Each row has the team logo (or a 28 × 28 monogram chip when there's none, per the design guide), the team name, and "N left", or "Complete" (dimmed, disabled) when the player owns every card of that team,
    - rows are sorted with available teams first, then alphabetically, and Complete teams last,
    - selecting a row marks it (orange border and accent-ghost background, `aria-pressed`),
    - the list scrolls, while **Draw from {team} · 3** stays **pinned at the bottom of the panel**. The button stays disabled until a team is picked or while the player has fewer than 3 tokens, with the note "You need 3 tokens for a team draw".
    
    The tiles come from `GET /twitch/teams`, which reuses the website's team-draw data (`GET /deck/booster`: teams with players who have match data, and the number left for this player). The draw calls `POST /twitch/draw/booster/{team_id}` (`draw_booster`).
  - The panel shows the drawn card (card art in its rarity treatment, name, team, rarity, and where it went: roster or bench) and refreshes the collection and token count.
  - **Collection:**
    - a count ("22 cards"),
    - **rarity filter chips with counts** (All, Leg, Epic, Rare, Com),
    - a five-per-row grid of small card art (48 × 66) with names, sorted rarest first, then by name.
    
    It scrolls inside the panel, and 40 cards stay usable.
- **Roster tab:**
  - shows the editable week's roster (up to the roster limit, default 5), the bench, the lock countdown and the week's points so far, from `GET /twitch/me`,
  - **Changing the roster starts from a slot**, because a season's bench (15–35 cards) is too long to scroll between bench and slots:
    - an empty slot shows **+ Add a card**, and a filled slot shows **Change**,
    - either opens a **bench picker for that slot**: "Pick a card for slot N" or "Replace in slot N", with **Back**,
    - the picker has **rarity filter chips with counts**, **sort by Points (season) or Rarity**, and one row per bench card (art, name, team, rarity, season points),
    - when the slot is filled, "In this slot: {name}" offers **Bench it** (`POST /twitch/roster/deactivate/{card_id}`, `deactivate_card`).
    
    Tapping a bench card places it in an empty slot (`POST /twitch/roster/activate/{card_id}`, `activate_card`) or swaps it with the slot's card (`POST /twitch/roster/swap`, `swap_roster`, the same swap the website's drag-and-drop uses). The panel then returns to the roster with a confirmation line ("Savu in, Pikkis to the bench.").
  - The Roster tab itself stays short: the five slots, the lock countdown, and the bench count.
  - All roster changes follow the website's limits and locked-week rules. The panel has no drag-and-drop.
- **Scoring:** soft accounts score exactly like website accounts. Their roster is snapshotted at the weekly lock and gets bench substitutions and stored card points (#129, #141).
- **Tokens:** soft accounts get the weekly token grant (`auto_lock_weeks` gives every user +1), drops and the season reset like everyone else.
- **Design:** the panel follows the site's design guide (`.claude/skills/README.md`, `design/colors_and_type.css`, `design/ui_kits/fantasy_web/`):
  - Big Shoulders all-caps display type, the orange accent on near-black neutrals, and rarity colours on card art and badges only,
  - 4 px buttons with no pill shapes,
  - 6 px cards with hairline borders,
  - the 2 px orange underline on the active tab,
  - focus rings,
  - no emoji,
  - the readability floor from the Weekly Report (no text under 11 px, `--fg-muted` or brighter for readable text, tabular numerals for points).
  
  Card art uses the UI kit's rarity treatment (tinted art with the glow on the art only).
- **Failure paths:**
  - drawing with too few tokens returns the same error as the website (409 "Not enough tokens"), and the button is disabled,
  - picking a team whose cards the player all owns isn't possible (tile disabled), and a stale request is refused with the website's draw_booster error (409 "No players available for this team"),
  - a locked week's roster is read-only, with "Roster locked for this week": when no editable week exists and a locked week is in progress, the panel shows that week's snapshot and the roster endpoints return 409 "Roster locked for this week",
  - the panel's game endpoints reject a viewer who hasn't joined with 404 `not_joined`, and never act on another user's card (owner check, as on the website).

### Token Drops for Players on Twitch
**User story**
As a player watching a stream, I want MVP token drops to reach my Twitch account so that watching is rewarded on Twitch.

**Acceptance criteria**
- **Who is eligible:** when the broadcaster confirms an MVP, the drop pool is every present viewer (heartbeat within the presence window) who has an account, soft or website-linked, via `users.twitch_user_id`. `TWITCH_DROP_MAX` and the one-drop-per-match rule are unchanged.
- **Heartbeat:** the panel sends the existing presence heartbeat only for joined viewers.
- **Chat:** the announcement names the MVP. Winners appear as "N viewers received a token", with no usernames, because soft accounts have none and the website username of a linked player shouldn't be revealed in chat.
- **In the panel:** a winner's panel shows "+1 token from the MVP drop" through the existing PubSub message and refreshes `GET /twitch/me`.
- **Kill switch:** `TWITCH_DROPS_ENABLED` (default `true`) turns drops off if Twitch asks. While it's false, confirming an MVP sets the MVP and the fantasy bonus only.
- **Failure path:** with no joined viewers present, the MVP is still set and the chat says no tokens were dropped.

### No Link Codes in the Extension
**User story**
As the extension's publisher, I want the panel to contain no link-code step so that nothing in the extension points to the website.

**Acceptance criteria**
- **Panel:** `#view-unlinked`, `#link-code-input`, `#btn-link` and the "Log into kana-cards.com" steps are removed. The panel no longer calls `POST /twitch/link`.
- **Players linked before:** a website account whose `twitch_user_id` matches the viewer's opaque id is treated as joined. The panel shows that account's tokens, collection and roster, and it receives drops as before.
- **Website Profile:** "Generate Twitch Code" is hidden. In its place is the note "Connecting Twitch to your account is coming soon". `POST /twitch/link-code` and `POST /twitch/link` stay unused until #160 replaces them. *(Done in #160: Profile offers Connect Twitch and the link routes are removed.)*
- **Failure path:** a linked player who presses Join gets their existing account back (the idempotent join). No duplicate soft account is created.

### Hidden, Private and Removable
**User story**
As a viewer, I want my soft account kept private and easy to remove, and as an admin I want to see and manage soft accounts, so that the system stays fair and lawful.

**Acceptance criteria**
- **Hidden from rankings:** soft accounts (`account_type="twitch"`) are excluded wherever users are ranked or shown publicly:
  - the season and weekly leaderboards (alongside the existing `is_tester = 0` filter),
  - season standings and End Season archives (`season_archive`),
  - user search and tag lists.
- **Admin users list:** soft accounts appear under a **Twitch viewers** filter as "Twitch viewer #{id}", with tokens, card count, created and last seen. They have no password actions; delete is available.
- **Leave:** **Leave Kana Cards** in panel Settings calls `POST /twitch/leave`:
  - for a soft account, it deletes the account and all its rows (cards, card points, roster entries, per-user state) and writes `twitch_soft_account_deleted`,
  - for a linked website account, it only clears `twitch_user_id`. That's an unlink, and the website account keeps everything.
- **Retention:** soft accounts with no activity (`last_seen_at`) for `TWITCH_SOFT_ACCOUNT_RETENTION_DAYS` (default 365) are deleted by a daily background job, with an audit entry.
- **Privacy text:** `frontend/privacy.html`, `frontend/terms.html` and the extension listing describe what's stored (opaque Twitch id, game progress, timestamps), why, and how to leave.
- **No public Twitch ids:** no public or player-facing endpoint, website or EBS, returns `twitch_user_id` or `twitch_account_id`. The only exception allowed is the admin users list, which in the implementation returns only booleans (`twitch_linked`, `twitch_identity_shared`). `GET /twitch/me` returns the player's game state, never their Twitch ids. A test checks every route's response for these field names, and admin exports leave them out.
- **No password requests:** the extension listing and the privacy page say "Kana Cards never asks for your Twitch or website password inside Twitch." The panel never shows a password field.
- **Failure path:** leaving twice, or leaving without an account, returns 200 with no change.

## Twitch Account Connection (Part 2, #160)

### Connect Twitch on the Website
**User story**
As a player logged in on kana-cards.com, I want to connect my Twitch account by signing in to Twitch so that my Twitch play and my website account are linked securely, without codes.

**Acceptance criteria**
- **The Profile section:** "Twitch" shows one of:
  - **Connect Twitch** when no Twitch account is connected,
  - "Connected to Twitch" with **Disconnect** when one is,
  - the merge prompt when a Twitch collection is waiting (next story).
- **Starting the sign-in:** Connect Twitch navigates to `GET /auth/twitch/start`, which requires a recent password check (`POST /reauth`). Without one it redirects back to `/#profile?twitch=reauth_required`; Profile opens the existing in-page password prompt and then navigates to start again. With one, start:
  - stores a sign-in attempt in `twitch_oauth_states`: a SHA-256 hash of a random `state`, the user id, a random `nonce`, the PKCE verifier if used, and an expiry 10 minutes ahead,
  - redirects to Twitch's authorize URL with `response_type=code`, `scope=openid`, the exact registered `redirect_uri`, `state`, `nonce` and, if supported, `code_challenge`.
- **Finishing the sign-in:** `GET /auth/twitch/callback?code&state`:
  1. **Check the attempt:** the `state` hash must exist, be unexpired, belong to the current website session's user, and be unused. The attempt is consumed on first use.
  2. **Exchange the code:** server-side, at the token endpoint, with the client secret.
  3. **Verify the ID token:** RS256 signature against Twitch's keys, `iss`, `aud` equal to the client id, `exp`, and `nonce` equal to the stored nonce.
  4. **Keep only the Twitch user id:** take `sub`. The access and refresh tokens are discarded and never stored or logged.
  5. **Store it:** set `twitch_account_id = sub` on the website account, and audit `twitch_connected`. `users.twitch_account_id` is unique, so if a soft account S holds `sub` (identity share), the id moves from S to the website account W in the same transaction and `W.pending_merge_user_id = S.id` records the waiting merge. S keeps its opaque `twitch_user_id`, so the panel keeps acting as S until the merge.
  6. **Return to Profile** (`/#profile?twitch=<key>`, no Twitch data in the URL). With a pending merge, Profile opens the merge prompt.
- **Conflicts:** if another website account already has this `twitch_account_id` (soft accounts never count as a conflict), or this account already has a different one, the callback stores nothing and returns to Profile with "This Twitch account is connected to another Kana Cards account" or "Disconnect your current Twitch account first".
- **Failure paths** (each returns to Profile with a neutral error, stores nothing and doesn't log any Twitch token):
  - a missing, expired, reused or someone else's `state`,
  - Twitch reporting an error (the user cancelled),
  - a failed code exchange,
  - an ID token that fails any check,
  - a callback without a website session.

### Merge My Twitch Collection
**User story**
As a player who played on Twitch before connecting, I want to move my Twitch cards and tokens into my website account, after seeing what will move, so that everything is in one place.

**Acceptance criteria**
- **The prompt:** when the website account W has a pending merge (`pending_merge_user_id` = soft account S, recorded at connect time, or when S shares its identity after W connected), Profile shows "Your Twitch collection: {cards} cards, {tokens} tokens. Add it to this account?" with **Add to my account** and **Not now**.
- **The call:** **Add to my account** calls `POST /twitch/merge/confirm`, which requires a recent password check. In one transaction it:
  - moves every card of S to W's **bench** (`is_active=false`, `slot_index=NULL`); duplicates are kept, and card points follow the card,
  - adds S's tokens to W,
  - deletes S's locked-week `weekly_roster_entries`, so W's past weekly scores and the leaderboards don't change,
  - deletes S and all its remaining rows through Part 1's `soft_accounts.delete_soft_account` (extended there if the merge needs more, never a second, narrower list), after the cards have moved to W,
  - sets `W.twitch_user_id = S.twitch_user_id` (clearing it on S first) so the panel recognises W,
  - writes `twitch_account_merged` with both ids and the counts moved.
  
  It returns the counts, and Profile shows "12 cards and 4 tokens added".
- **One merge per website account, ever:** a website account that already absorbed a soft account (recorded in the audit log and a `users.merged_soft_account_at` timestamp) gets 409 for any further merge.
- **Not now** keeps both accounts as they are (the pending merge stays). The prompt shows again on the next Profile visit.
- **Failure paths:**
  - no pending soft account gives 404,
  - a stale prompt (S already merged, left or purged) gives 404 with a refresh, and the pending id is cleared,
  - an error part-way through rolls the whole merge back; a test injects one,
  - a merge without a recent password check gives 403 `reauth_required`.

### Recognised in the Panel After Connecting
**User story**
As a player who connected Twitch on the website, I want the extension to recognise my website account so that drops, draws and my roster use that one account.

**Acceptance criteria**
- **Lookup order:** in `POST /twitch/join`, `GET /twitch/me` and every panel game route: (a) the account whose opaque `twitch_user_id` matches the JWT; (b) else the account whose `twitch_account_id` equals the JWT's `user_id`, which is recognised (the opaque id is attached), so Join returns it (never 409 `twitch_identity_in_use`, never a new soft account) and `GET /twitch/me` reports it as joined; (c) else Join creates a soft account.
- **Recognising the website account:** when a panel request carries a Twitch JWT with `user_id = X`, and website account W has `twitch_account_id = X`:
  - **If no soft account uses the viewer's opaque id:** W's `twitch_user_id` is set to the JWT's opaque id. From then on the panel acts as W (its tokens, collection and roster), and W receives drops.
  - **If a soft account S still uses that opaque id (merge not confirmed yet):** the panel keeps acting as S until the merge is confirmed on the website. The panel says nothing about the website.
- **Website guidance:** if S never shared its identity (no `twitch_account_id`), the website can't find it. When S shares it later, S becomes W's pending merge. Profile explains: "Joined on Twitch first? In the Kana Cards Twitch panel, open Settings and choose Share your Twitch identity, then reload this page." This text is on the website only.
- **Failure path:** a JWT without `user_id` (no identity share) never changes which account the panel acts as.

### Disconnect and Retire Link Codes
**User story**
As a player, I want to disconnect Twitch from my account, and as the publisher I want the old link-code mechanism gone, so that only the secure flow remains.

**Acceptance criteria**
- **Disconnect:** **Disconnect** (recent password check) calls `POST /twitch/disconnect`, which clears `twitch_account_id`, `twitch_user_id` and any pending merge on the website account and audits `twitch_disconnected`.
  - The website account keeps its cards and tokens.
  - In the panel the viewer is "not joined" again and can join a new soft account.
  - The one-merge limit still applies to that website account.
- **Retired:** `POST /twitch/link-code`, the code-based `POST /twitch/link`, the legacy `GET /twitch/status` (returns a username; superseded by `GET /twitch/me` in Part 1), the `TwitchLinkCode` usage and the old Profile code UI are removed. Requests to the removed endpoints get 404. The `twitch_link_codes` table and the `TwitchLinkCode` model remain for a later clean-up migration; only `soft_accounts.delete_soft_account` still deletes its rows, and no route reads or writes it.
- **Configuration:** `TWITCH_OAUTH_CLIENT_ID`, `TWITCH_OAUTH_CLIENT_SECRET` and `TWITCH_OAUTH_REDIRECT_URI` in `.env.example`, with comments. When any is missing, the Profile shows "Connecting Twitch is not available right now." instead of Connect Twitch, `GET /auth/twitch/start` returns 503, and the app still starts.
- **Docs:** the privacy page describes the Twitch connection: the stored Twitch user id, and that tokens aren't stored.
- **Failure path:** a disconnect without a connected account returns 200 with no change.

### Recoverable and Contained
**User story**
As the operator of a hobby project, I want a bad merge to be reversible, the feature easy to switch off, and Twitch identities never exposed, so that an incident stays small and fixable.

**Acceptance criteria**
- **Merge undo log:** before deleting the soft account, `merge_soft_into` writes one `twitch_merge_log` row:
  - `id`, `full_user_id`, `merged_at`,
  - `soft_snapshot` (JSON): the soft account's `twitch_user_id`, `twitch_account_id`, `created_at`, `last_seen_at` and `tokens`,
  - `card_ids` (JSON),
  - `tokens_moved`,
  - `roster_entries` (JSON of the deleted locked-week rows: week, card, bench flags, substitution flags),
  - `reversed_at`.
  
  Rows older than 30 days are deleted by a daily job. The deleted per-user rows (reveals, seen, dismissals, claims, redemptions) aren't snapshotted. A reversal doesn't restore them; that's minor and documented.
- **Admin reverse:** `POST /admin/twitch/merges/{log_id}/reverse` (admin, recent password check) undoes a merge within 30 days, in one transaction:
  - recreates the soft account (new id) from the snapshot,
  - moves the logged cards it still finds on the website account back to it,
  - subtracts `tokens_moved` from the website account, never below 0, and records any shortfall in the reply and the audit log,
  - restores the logged locked-week roster entries,
  - clears the website account's `twitch_account_id`, `twitch_user_id` and `merged_soft_account_at`, so the legitimate owner can connect and merge again,
  - sets `reversed_at` and audits `twitch_merge_reversed`.
  
  Admin › Users shows recent merges (`GET /admin/twitch/merges`, admin and recent password check, with a `reversible` flag) with a **Reverse** button.
- **Reversal failure paths:** a log row older than 30 days, already reversed, or crossing a season reset (its cards no longer exist) returns 409 with a clear message, and nothing changes.
- **Kill switches, documented:**
  - unsetting any `TWITCH_OAUTH_*` variable turns Connect Twitch off (hidden on Profile, 503 on start) without affecting existing connections or the panel,
  - `TWITCH_DROPS_ENABLED=false` (from #157) stops drops.
  
  Both are listed in the incident runbook.
- **Incident runbook:** `markdown/features/reference/twitch-incident-runbook.md`, covering:
  1. switch off with the kill switches,
  2. rotate the client secret and the extension secret in the Twitch console, and update the env,
  3. review the audit log for `twitch_connected`, `twitch_account_merged` and `twitch_disconnected` in the window,
  4. reverse bad merges from the undo log, or restore the pre-deploy backup (`scripts/backup-db.sh`),
  5. check the registered redirect addresses,
  6. post a short, honest note to players.
- **No public Twitch ids:** no endpoint returns `twitch_user_id` or `twitch_account_id`. `GET /twitch/connection` returns only `available`, `connected`, `pending_merge` counts, `merge_used` and `last_twitch_activity_at`, never an id, and since Part 1 the admin users list returns only the booleans `twitch_linked` and `twitch_identity_shared`. A test checks every route's response model or schema for these field names. Admin exports also leave out Twitch ids.
- **Takeover containment:**
  - the panel offers nothing irreversible for a website-linked account: Leave only unlinks, and no panel action deletes cards or changes website credentials,
  - Profile shows "Last Twitch activity: {date}" from `last_seen_at` (returned by `GET /twitch/connection` as `last_twitch_activity_at`; written by panel calls at most once an hour, #157), so a player can notice unexpected use and press Disconnect.
- **Secrets stay out of logs and backups:**
  - a test drives the callback through success and every failure path while capturing logs, and asserts that the authorization code, the ID and access tokens and the client secret never appear,
  - another test asserts that `scripts/backup-db.sh` copies only the database file and never `.env`.
- **We never ask for passwords:** the website's Profile Twitch section and the privacy page say "Kana Cards never asks for your Twitch or website password inside Twitch."

---

## MVP Selection Delays (#161)

### Live Games Come From Steam
**User story**
As a caster for Kanaliiga, I want the app to detect my live game from Steam's league list, so that early MVP selection works for amateur matches that OpenDota's live list doesn't show.

**Acceptance criteria**
- With `STEAM_API_KEY` set, each live check calls Steam's `IDOTA2Match_570/GetLiveLeagueGames` once, and keeps only games whose `league_id` is monitored.
- Each game is normalised to the entry shape `store_live_matches()` reads:
  - `match_id`, `league_id`,
  - team ids (0 or missing stored as `NULL`), team names (`""` stored as `NULL`),
  - `players` with `account_id`, `name`, and `team` (0 radiant, 1 dire).
- Players with a `team` other than 0 or 1, and players without an `account_id`, are skipped.
- OpenDota's `/live` is no longer called anywhere. `get_live_matches()` is removed, and the ingest loop and its tests no longer use it.
- The Steam key is never logged, stored or returned in a response. Request errors are logged with the HTTP status or exception class only, never the URL.
- Failure path: with `STEAM_API_KEY` unset, no live check runs. A warning is logged once at start-up, and `GET /twitch/matches/current` reports `live_source_configured: false`.

### Live Matches Appear in the MVP Picker Within a Minute
**User story**
As a caster, I want the match I'm casting to appear in the Twitch MVP picker within about a minute of the game starting, so that I can pick the MVP when the game ends instead of an hour later.

**Acceptance criteria**
- Live games are checked by a background thread of their own, `_live_poll_loop`, every `LIVE_POLL_INTERVAL` seconds (default 60) whenever at least one league is monitored and `STEAM_API_KEY` is set. It never waits on ingest, enrichment, parse retries or the Toornament sync.
- Each check makes one Steam request with a timeout of 10 s and no retries or backoff sleeps. A failed check is logged and retried on the next tick.
- `_ingest_poll_loop` makes no live calls. To choose its interval, and whether to skip enrichment, it reads `live_matches`: a game with `ended_at IS NULL` that was seen in the last 15 minutes counts as live.
- In `DEMO_MODE` the live thread doesn't start, as for the ingest thread.
- Failure path: a failed Steam request leaves `live_matches` unchanged. It doesn't mark stored games ended.

### See Where the Delay Comes From
**User story**
As an admin, I want to see for each recent match when it was first seen live, when its stats arrived and when its MVP was picked, so that I can tell whether casters are waiting on live detection, on OpenDota or on something else.

**Acceptance criteria**
- A `match_timings` row per match records:
  - `live_first_seen_at`, set by the live thread on first sight,
  - `ingested_at`, set by `ingest_match()` when stats are written,
  - `mvp_confirmed_at` and `mvp_provisional` (true when the MVP was confirmed before ingest), set by `POST /twitch/mvp`.
  
  Each field is set only while it's empty, so `mvp_confirmed_at` is the first confirmation.
- `GET /admin/matches` includes `live_first_seen_at`, `ingested_at` and `mvp_confirmed_at` for each match.
- The admin Matches table shows "Live seen", "Stats in" and "MVP picked", each as minutes after the match's `start_time` (e.g. "+2 min", "+58 min"), with "—" when unknown. Hovering a value shows the exact time.
- Failure path: a match that was never seen live shows "—" under "Live seen", which marks it as missed by live detection.

### Casters Can See How Fresh the Match List Is
**User story**
As a caster, I want the MVP picker to tell me when it last checked for live games and let me refresh it, so that I know whether to wait or whether something is wrong.

**Acceptance criteria**
- `GET /twitch/matches/current` returns:
  - `live_checked_at`: the Unix time of the last successful live check, or `null` if there hasn't been one since start-up;
  - `live_source_configured`: whether `STEAM_API_KEY` is set.
- The panel's series list shows "Live games checked N s ago" (or "N min ago"), and a Refresh button that fetches the list again.
- When `live_checked_at` is more than 5 minutes old or `null`, or the source isn't configured, the line reads "Live games not checked recently — your match will appear once its stats are in" in the warning colour.
- Failure path: if the request fails, the panel shows its existing error state and the Refresh button stays usable.

---

## Twitch Panel Abuse Limits (#171)

### New Accounts Wait a Day Before Joining Drops
**User story**
As a viewer, I want drops to go to real viewers, so that someone who makes a stack of Twitch accounts during a broadcast can't crowd out my chance to win.

**Acceptance criteria**
- `_active_pool` includes a soft account only when `users.created_at` is at least `TWITCH_DROP_MIN_ACCOUNT_AGE_HOURS` (default `24`) before the drop. Website accounts are always included. `0` turns the age rule off.
- The panel tells a newly joined viewer: "Drops start for your account on <date>." It does this in the Live tab until the account is old enough.
- Each `twitch_token_drop` audit entry keeps `count=<winners>` and adds `pool_size=<n>` and `excluded_new=<count>`.
- When the pool is empty only because every present account is too new, the server still writes a `twitch_token_drop` entry with `count=0 pool_size=0 excluded_new=<count>`. The drop is not claimed, so a later confirmation of the same match can still drop. Chat then says "No tokens were dropped: new accounts join drops <N> hours after joining." (the configured age) instead of "no joined viewers were watching."
- When a drop's `pool_size` is more than three times the median of that channel's last ten `twitch_token_drop` entries (only with at least five earlier entries), the server logs a warning and the audit detail includes `pool_spike=true`. Entries without `pool_size=` (written before #171) and empty pools are left out of the median.
- **Failure path:** a soft account created one hour before a drop is not in the pool and gets no token. The drop still goes to the eligible viewers, and the chat count reflects only them.

### Logged-Out Viewers Don't Fill the Presence Table
**User story**
As the operator, I want heartbeats from logged-out viewers to be ignored, so that people who can't join or win don't add rows or load.

**Acceptance criteria**
- `POST /twitch/heartbeat` with an opaque id not starting with `U` returns `{"ok": true}` and writes no `twitch_presence` row.
- The route is limited per viewer (`key_by_twitch_viewer_or_ip`, `RATE_LIMIT_TWITCH_ACTION`) and per IP (`RATE_LIMIT_TWITCH_JOIN_IP`), like the other panel routes.
- **Failure path:** a heartbeat with an `A…` id leaves `twitch_presence` unchanged, and a `U…` heartbeat still upserts its row.

### Team Logos Only From Known Hosts
**User story**
As a viewer, I want team logos to load only from known image hosts, so that opening Kana Cards or the panel doesn't show my IP address to arbitrary servers.

**Acceptance criteria**
- A new `backend/logo_hosts.py` has `safe_logo_url(url) -> str | None`. It returns the URL only when it is `https:`, has no explicit port and no userinfo (`user@host`), and its host is in `LOGO_HOST_ALLOWLIST`:
  - comma-separated, compared case-insensitively;
  - an empty value falls back to the default Steam CDN list.
  
  Otherwise it returns `None`.
- `ingest._match_logo_url` turns `//host/...` into `https://host/...` and then stores only URLs that pass `safe_logo_url`.
- Every response that carries `team_logo_url` or a team `logo_url` passes it through `safe_logo_url`: the card and roster routes, `GET /deck/booster`, the panel's teams and collection, and the Weekly Report fallback. `GET /teams` and `GET /teams/{team_id}` return no logo field, and the schedule returns no logos. The local `/assets/` logo stays preferred wherever it is used today.
- The card image (`GET /cards/{card_id}/image`) also passes the logo through `safe_logo_url` before the server fetches it, so the server never requests a logo from an unknown host.
- When the logo is `null`, the panel shows the team monogram, the website's team draw shows its blank circle placeholder and the Weekly Report shows the team name alone. This already happens for teams without a logo.
- **Failure path:** a team whose stored `logo_url` is `https://evil.example/logo.png` is returned with `logo_url: null`, and an ingest of such a URL stores nothing.

### Only Our Extension Can Call the Backend Cross-Origin
**User story**
As the operator, I want CORS to allow only our own extension's origin, so that another extension's iframe gets no `Access-Control-Allow-Origin` from our backend.

**Acceptance criteria**
- With `TWITCH_EXTENSION_CLIENT_ID=abc123`, a preflight from `https://abc123.ext-twitch.tv` gets `Access-Control-Allow-Origin` and one from `https://other999.ext-twitch.tv` doesn't.
- The client id is regex-escaped when the rule is built.
- Without `TWITCH_EXTENSION_CLIENT_ID`, no `*.ext-twitch.tv` origin is allowed. A warning is logged once at start-up, and `CORS_EXTRA_ORIGINS` origins keep working.
- `allow_credentials` stays false.
- **Failure path:** a preflight from another extension's origin gets no `Access-Control-Allow-Origin` header.

---

## Approved Streamers Admin (#175)

Plan: `markdown/plans/plan-issue-175-approved-streamers-admin.md`.

### Broadcaster Asks to Be Approved
**User story**
As a broadcaster who installed the extension, I want the MVP tool to tell me my channel is waiting for the league's approval so that I know why I can't set MVPs yet and that the league has been asked.

**Acceptance criteria**
- When a channel that isn't approved opens the MVP tool (`GET /twitch/matches/current` with `role: broadcaster`) or tries `POST /twitch/mvp`, the backend records a pending request for that channel id, with first and last seen times; repeated visits update the last seen time and create no duplicates
- `GET /twitch/matches/current` returns `mvp_allowed` (true or false) and `approval` (`approved`, `pending` or `rejected`)
- When `mvp_allowed` is false, the MVP tool shows "This channel is waiting for the league's approval to set match MVPs." instead of the series list (`rejected`: "This channel isn't approved to set match MVPs.")
- `POST /twitch/mvp` from a channel that isn't approved still returns 403 before any MVP, bonus or drop is written
- Viewer and moderator tokens never create a request
- A rejected channel's later visits update its last seen time but don't move it back to pending

### Approve Streamers in the Portal
**User story**
As an admin, I want to see channels waiting for approval and approve or reject them in the portal so that adding a streamer doesn't need a server change.

**Acceptance criteria**
- The admin panel has an **Approved streamers** section with three lists: Waiting for approval, Approved, and Rejected (collapsed)
- Each row shows the Twitch display name and login when known, the numeric channel id, and first and last seen dates
- **Approve** on a waiting or rejected channel makes it approved at once: its next MVP confirmation is accepted
- **Reject** on a waiting channel moves it to Rejected; **Remove** on an approved channel moves it to Rejected
- Approve, Reject and Remove ask for the admin's password if it wasn't confirmed in the last 10 minutes, and each writes an audit entry (`twitch_channel_approved`, `twitch_channel_rejected`, `twitch_channel_removed`) with the channel id
- Channels from `TWITCH_MVP_CHANNEL_IDS` are listed as Approved with a "from server settings" note and no Remove button
- Non-admins get 403 on every endpoint

### Env Var and Portal Together
**User story**
As the league operator, I want the existing `TWITCH_MVP_CHANNEL_IDS` setting to keep working alongside the portal so that nothing breaks when this ships.

**Acceptance criteria**
- A channel may set MVPs when it is in `TWITCH_MVP_CHANNEL_IDS` or approved in the portal
- With both lists empty, no channel may set MVPs when `ENV=production` and any channel may otherwise (unchanged from #165); the start-up warning names both places
- Removing a channel in the portal never affects a channel that is also in the env var
