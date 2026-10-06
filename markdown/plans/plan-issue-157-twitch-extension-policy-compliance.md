# Plan: Twitch Extension Policy Compliance (Part 1 of 2)

## Context
Twitch's review rejected the extension under policy **4.5**: *"Extensions may not encourage or reward users to take specific actions outside Twitch/Amazon properties, especially if the principal use case for the Extension is to act as a link out or a call-to-action."* The stated violation: **"Extensions cannot require viewers to login to external sites in order to use them."**

**Why it fails today:**
- **The panel opens on a login prompt.** The viewer panel (`twitch-extension/panel.html`) opens on "Log into **kana-cards.com** → Profile → Generate Twitch Code → enter the code".
- **Linking is the only viewer value.** After linking, the panel only shows a token balance, and the viewer becomes eligible for token drops. Those are Kana Cards tokens that can only be spent on the website.

**The outcome: the extension becomes a complete game on Twitch.**
- **No sign-up needed to watch:** any viewer sees live fantasy information (MVPs, top performers, next match).
- **Join on Twitch:** a viewer logged in to Twitch presses **Join Kana Cards**. The backend (EBS) creates a **soft account** keyed by their opaque Twitch id, with no username, email or password.
- **Play in the panel:** soft accounts receive MVP token drops, draw cards (regular and team draw), keep a collection and set their weekly roster, all inside the panel.
- **Optional website account (Part 2, #160):** a player who also wants a kana-cards.com account can connect the two later. That uses Twitch's own sign-in on the website and merges the soft account into the website account. Part 1 prepares for it by storing the viewer's real Twitch user id at Join, through Twitch's identity share.

The extension never requires, mentions or pushes the website.

Mockups: https://claude.ai/artifact/T4DvumfGSTbXdXTZNodkWx
- **Panel (318 × 500):** interactive, with Live, Cards and Roster tabs.
- **Panel states:** not joined, card reveal, roster.
- **Larger video component** docked over the stream, as a possible later surface.

**Decisions by the product owner (2026-10-05):**
- Soft accounts are `users` rows. Their creation rules are specified in full below; the merge rules are in #160's plan.
- The work is split into two issues: this plan (#157, what the resubmission needs) and #160 (Connect Twitch with Twitch sign-in, the merge, retiring link codes).
- Card draws, the collection and the roster all live in the extension, in this plan.
- Soft accounts are hidden from every leaderboard and from season standings.

**Assumptions:**
- **Twitch ids:** a viewer logged in to Twitch has a stable opaque id starting with `U` for this extension; logged-out viewers get a temporary `A…` id. Only `U…` viewers can join. Logged-out viewers see the live information and a "Log in to Twitch to join" note. Logging in to Twitch is a Twitch action, so it's allowed.
- **Identity share at Join:** Join calls `Twitch.ext.actions.requestIdShare()`, which shows Twitch's own consent dialog. When the viewer agrees, the Twitch-signed extension JWT carries `user_id` (the real Twitch user id), stored as `users.twitch_account_id`. #160 matches it against the website's Twitch sign-in. A viewer who declines still gets a soft account, keyed by the opaque id only. Asking for the identity share is a Twitch action, so it's allowed under 4.5.
- **Reuse:** the panel's game actions call the same functions the website uses (`draw_card`, `draw_booster`, `activate_card`, `deactivate_card`, `swap_roster` in `routers/cards.py`, and `_build_roster_response`), with the soft account as the acting user. The demo-account seeding already calls `draw_card(db=db, current_user=…)` this way.
- **Season scale:** the panel is designed for a season with **14 teams**, and for players who hold **about 20 cards** by season end, more (30–40) if drops work as intended. So:
  - the team picker uses compact two-column rows with the draw button pinned,
  - the roster is changed starting from a slot, not from the bench,
  - the collection and bench have rarity filters and sorting.
  
  Everything must stay usable inside the 318 × 500 panel.
- **Scope:** the panel is the only surface in this plan. The video component in the mockups is a follow-up.
- **Database changes:** three new columns on `users` (`account_type`, `last_seen_at`, `twitch_account_id`), which need a numbered migration (`031`). There are no new tables and no account data is deleted.
- **Linking between the two parts:** the panel's link-code entry goes away now, to meet the policy. Accounts linked by code before this change keep working, because the panel recognises them by `users.twitch_user_id`. New links between a website account and Twitch become possible again with #160. Until then, Profile hides "Generate Twitch Code", since there's nowhere to enter the code.
- **Steam login (#150):** a future Steam website account connects Twitch the same way (#160).

Resolves GitHub issue #157. Part 2: #160.

## User Stories

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
  - picking a team whose cards the player all owns isn't possible (tile disabled), and a stale request is refused with the website's draw_booster error (409 "No players available for this team"; the website itself would draw a duplicate),
  - a locked week's roster is read-only, with "Roster locked for this week",
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
- **Website Profile:** "Generate Twitch Code" is hidden. In its place is the note "Connecting Twitch to your account is coming soon". `POST /twitch/link-code` and `POST /twitch/link` stay unused until #160 replaces them.
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
- **No public Twitch ids:** no public or player-facing endpoint, website or EBS, returns `twitch_user_id` or `twitch_account_id`. The only exception is the admin users list. `GET /twitch/me` returns the player's game state, never their Twitch ids. A test checks every route's response for these field names, and admin exports leave them out.
- **No password requests:** the extension listing and the privacy page say "Kana Cards never asks for your Twitch or website password inside Twitch." The panel never shows a password field.
- **Failure path:** leaving twice, or leaving without an account, returns 200 with no change.

## Implementation

### Critical Files
| File | Change |
|---|---|
| `backend/models.py` | `User.account_type` (String, NOT NULL, default `"full"`), `User.last_seen_at` (Integer, nullable), `User.twitch_account_id` (String, nullable, unique) |
| `backend/migrate.py` | Migration `031_users_twitch_soft_accounts` (PRAGMA-guarded `ALTER TABLE … ADD COLUMN` for the three columns, existing rows get `"full"`, plus a unique index on `twitch_account_id`) |
| `backend/soft_accounts.py` (new) | `get_or_create_soft_account`, `record_twitch_account_id`, `delete_soft_account`, `purge_inactive_soft_accounts`, all transaction-safe (`merge_soft_into` comes in #160) |
| `backend/twitch.py` | `GET /twitch/panel`, `POST /twitch/join`, `GET /twitch/me`, `POST /twitch/draw`, `POST /twitch/draw/booster/{team_id}`, `POST /twitch/roster/activate/{card_id}`, `POST /twitch/roster/deactivate/{card_id}`, `POST /twitch/roster/swap`, `GET /twitch/teams`, `POST /twitch/leave`; `twitch_account_id` recorded from JWT `user_id`; drop pool includes soft accounts; anonymous chat winners; `TWITCH_DROPS_ENABLED` gate |
| `backend/routers/cards.py` | Make sure the draw and roster functions can be called with a soft account's user dict, and add a small adapter if the `current_user` shape differs |
| `backend/routers/leaderboard.py`, `backend/routers/admin_season.py`, `backend/routers/admin_users.py`, user search and tag endpoints | `account_type = 'full'` filter for rankings, archives and search; admin Twitch viewers filter |
| `backend/main.py` | Daily retention job alongside the existing background loops; register the new env vars |
| `twitch-extension/panel.html`, `panel.js`, `extension.js`, `extension.css` | Live / Cards / Roster tabs, Join with identity share, draw reveal, collection, roster, Settings (share identity, leave); link-code UI removed; no login text; heartbeat only when joined |
| `twitch-extension/live_config.*`, `config.html` | Anonymous winner count; no viewer call-to-action |
| `twitch-extension/package.sh` | Version 1.2.0; forbidden-text self-check |
| `frontend/index.html`, `frontend/app-profile.js` | Profile hides "Generate Twitch Code" and shows "Connecting Twitch to your account is coming soon" (#160 replaces it) |
| `frontend/privacy.html`, `frontend/terms.html` | Soft-account data and leaving |
| `.env.example` | `TWITCH_DROPS_ENABLED`, `TWITCH_SOFT_ACCOUNT_RETENTION_DAYS` |
| `markdown/features/reference/twitch-extension-policy-compliance.md` and the other Twitch docs, `markdown/stories/twitch.md` | Docs |
| `backend/tests/test_issue_157_twitch_extension_policy_compliance.py` | API, identity share, privacy and static tests |

### Step 1 — Model and migration
- **Columns:** add `account_type` and `last_seen_at`, plus migration `031` per `CLAUDE.md`. `test_migrate.py` must pass.
- **Rule:** `account_type` is `"full"` for website accounts and `"twitch"` for soft accounts. Every place that ranks or lists users publicly filters on it.

### Step 2 — `soft_accounts.py`
```python
def get_or_create_soft_account(db, opaque_id: str, real_id: str | None) -> tuple[User, bool]: ...
def record_twitch_account_id(db, user: User, real_id: str) -> None: ...
def delete_soft_account(db, soft: User) -> None: ...
def purge_inactive_soft_accounts(db, now: int, days: int) -> int: ...
```

`record_twitch_account_id(db, user, real_id)` sets the column only when it's empty. It refuses (409) when another account already holds that id, and it never overwrites a different id.

### Step 3 — EBS endpoints
- **Auth:** all endpoints use `verify_twitch_jwt`. The game endpoints look the user up by `twitch_user_id`, return 404 `not_joined` when there's none, and build the `current_user` dict the card functions expect.
- **Rate limits:** per opaque id.
- **Responses:** never include `email`, `password_hash` or other users' data.

### Step 4 — Drops
- **Pool:** keep the pool query (presence joined to `users.twitch_user_id`), which now naturally includes soft accounts.
- **Chat:** the text names the MVP and the winner count only.
- **PubSub:** the message tells each winner's panel to refresh.
- **Kill switch:** add the `TWITCH_DROPS_ENABLED` gate.

### Step 5 — Hide soft accounts
Add `account_type = 'full'` filters to:
- the season, weekly and roster leaderboards (`routers/leaderboard.py`, next to `is_tester = 0`),
- `compute_season_standings` and the End Season archive,
- user search, tag grant lists and admin lists (admin lists get a filter rather than exclusion).

Check every `db.query(User)` caller (16) and record each decision in the feature doc.

### Step 6 — Panel
- **Tabs:** build the three tabs as in the mockup (Live; Cards with draw, reveal, collection and the team picker; Roster with tap-to-place and swap), plus a Settings view (Share your Twitch identity, Leave Kana Cards). Follow the design guide; the styles may be copied from `design/colors_and_type.css`, since the extension package is self-contained.
- **States:** not joined, joined, logged out of Twitch, locked week, out of tokens, EBS down.
- **Rendering:** all rendering escapes data. There's no emoji (the old 🎉 goes) and no kana-cards.com text.
- **Size:** keep to the 318 × 500 panel.

### Step 7 — Website, privacy, packaging
- **Profile:** hide "Generate Twitch Code" and show "Connecting Twitch to your account is coming soon".
- **Privacy and terms:** describe the soft-account data, including the optional real Twitch user id stored after the identity share, and how to leave.
- **Packaging:** `package.sh` builds version 1.2.0 with the self-check. Update the review notes and the listing text in `twitch-extension-review-submission.md`.

### Step 8 — Tests and docs
`backend/tests/test_issue_157_twitch_extension_policy_compliance.py`:
- **Join:**
  - creates exactly one account, idempotently, even with concurrent joins (simulated),
  - an `A…` id gets 403,
  - the soft account can't log in or be found by forgot-password.
- **`/twitch/me`:** the not-joined and joined shapes; no private fields.
- **Team picker:** `GET /twitch/teams` returns the same teams and "left" counts as `GET /deck/booster` for that player.
- **Swap:** `POST /twitch/roster/swap` puts the bench card in the slot and the replaced card on the bench, using the website's swap logic; locked weeks are refused.
- **Season points in `GET /twitch/me`:** each card carries its season points, so the bench picker can sort by them, and rarity for the filters. A player with 40 cards gets a complete response, with no paging needed.
- **Draws and roster for soft accounts:**
  - draws cost tokens, roll rarity and respect the roster limit and the locked week,
  - another user's card gets 403/404,
  - weekly lock, substitution and stored points include soft accounts.
- **Drops:**
  - the pool includes soft accounts,
  - the chat text has no usernames,
  - the kill switch works.
- **Identity share:**
  - `twitch_account_id` is stored from a JWT with `user_id`,
  - the column is never overwritten with a different id, and a duplicate gets 409,
  - declining still allows joining.
- **Players linked before:** a code-linked website account is recognised as joined, and Join returns it instead of creating a soft account.
- **Static checks:** no link-code UI or `/twitch/link` call remains in the panel, and Profile hides "Generate Twitch Code".
- **Hidden:** soft accounts are absent from the season and weekly leaderboards, standings, archives and search, and present in the admin Twitch viewers filter.
- **Leave and retention:** leave deletes a soft account but only unlinks a website account, and is idempotent; retention deletes only inactive soft accounts.
- **No public Twitch ids:** no public or player endpoint response (website or EBS) contains `twitch_user_id` or `twitch_account_id`.
- **No password field:** no viewer file has `type="password"`, and the listing text in the review doc contains the never-asks-for-passwords line.
- **Migration:** `031` adds the three columns on the legacy schema; existing users become `"full"`.
- **Static checks:**
  - the forbidden text is absent from the viewer files,
  - `package.sh` has the self-check and version 1.2.0,
  - the privacy page mentions soft accounts.

Then:
- bump the suite-size tripwire,
- update the Twitch feature docs, the stories and `.env.example`,
- fill in the stub, including a table of every `db.query(User)` caller and how it treats soft accounts.

## Verification
- **Twitch developer rig, logged out:** the Live tab works and Join reads "Log in to Twitch to join".
- **Logged in:**
  1. Join: the account is created, and the starting tokens show.
  2. Draw: the card reveal appears and the collection updates.
  3. Team draw: the picker lists all 14 teams in two columns, available first and Complete last, with the draw button pinned while the list scrolls. Drawing from a team gives one of its players.
  4. Roster: Add a card to an empty slot, Change a filled one (swap), and Bench it, all through the slot's bench picker with filters and sorting. The roster and bench match the website for the same account.
  5. Scale: with a seeded account of about 40 cards, the collection, the filters and the bench picker stay usable in the 500 px panel.
  6. After the weekly lock, the roster is read-only and its points accrue.
- **As the broadcaster:** confirm an MVP. Present joined viewers receive tokens, the panel shows the drop, and the chat names the MVP and the winner count only.
- **Website:** the soft account appears on no leaderboard. Admin › Users › Twitch viewers lists it.
- **Identity share:** Join shows Twitch's identity-share dialog. Agreeing stores the real Twitch id. Declining still joins, and Settings offers the share later.
- **Players linked before:** a code-linked website account opens the panel as joined, with its own cards, tokens and roster.
- **Leave:** from a soft account it removes all of the account's data. From a linked website account it only unlinks.
- **Review copy:** the extension shows no kana-cards.com text, and `package.sh` passes and builds 1.2.0.
- **Resubmission:** submit 1.2.0 with reviewer notes:
  - the panel works without an account,
  - Join uses only the Twitch login,
  - there is no link to the website.
  
- `cd backend && python3 -m pytest tests/ -q` passes.
