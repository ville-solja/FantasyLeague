# Plan: Pre-Season Team Signup

## Context
Issue #220 asks for a pre-season signup where partial teams can find each other. A captain logs in, lists their team with the Dota ids of the players they have and a way to be contacted, and browses the other listed teams and their players. The tournament organiser gets the listings as data they can use straight away.

The owner's follow-ups:
1. **Its own tab,** shown only while an admin has the signup period open.
2. **A design canvas first** to plan how partial teams and their players are shown, and what a fair way to promote teams is.
3. **The captain can mark the team full.**

**Timing:** milestone S17. It is used between seasons (after End Season and Reset, before the S17 leagues start), so it can't depend on this season's teams, leagues or weeks.

**What we have to build on:**
- **Accounts:** website accounts with optional Steam sign-in. Since #209, `User.player_id` is set only from a verified Steam login, so a captain with Steam linked has a known Dota id.
- **Players:** the `players` pool holds names and, since #221, `rank_tier` / `leaderboard_rank`. `player_rank.medal_name` formats them.
- **Typed-in Dota ids:** Admin › Player Management resolves typed ids to names from the pool or OpenDota (`routers/admin_players.py`: `_parse_lookup_ids`, `_opendota_name` with a bounded TTL cache). This helper moves to a shared module so captains can use it.
- **Steam ids:** `steam_openid.STEAM32_OFFSET` converts a Steam64 id to the 32-bit Dota id.
- **Names:** `text_safety.clean_display_text` and `looks_like_url` clean user-chosen names.
- **A tab gated by `GET /config`:** the Finals tab (#237, `finals_available` and `applyFinalsAvailability`) is the precedent.
- **Admin Settings:** Admin › Settings has a Season section (#214) where the signup controls fit.

**Decisions** (change them in review, and see the canvas in Step 1):
- **Tab:** **Team Finder**, between Schedule and How to Play.
  - It shows while a signup period is open (`GET /config` `team_signup_open`). Admins always see it.
  - When the period closes the tab hides. The listings stay for the admin export until they are cleared.
- **Signup period:** an admin opens a period with a label (for example "Season 17") and an optional closing time, and can close it early. One period is open at a time. Opening, closing and clearing are audited.
- **Who can list a team:** a logged-in website account. Twitch soft accounts can't: they have no website session (`deps._session_user` ignores them, so a request answers `401`; `team_signup.save_listing` also refuses one with `403`). One listing per account per period, so the account is the captain.
- **The listing:**
  - **Team name:** 2–32 characters, cleaned like usernames. A name that looks like a link is refused.
  - **Players:** 1–7 Dota ids (five players and up to two substitutes). The captain's own linked player is added first when Steam is linked.
  - **Open roles:** positions 1–5 the team still needs. Optional.
  - **Note:** 280 characters, cleaned, no links. Optional.
  - **Contact:** required, free text up to 100 characters (for example a Discord name), cleaned.
  - **Full:** a checkbox the captain sets when the team has its players.
- **Dota ids typed by the captain:**
  - accepted as the 32-bit Dota friend id or as a Steam64 id, which is converted;
  - each id is shown with its name and rank medal before saving: from the pool, otherwise from OpenDota (cached like the admin lookup; capped at 20 uncached ids per user and 60 in total per hour, never waiting for the shared OpenDota rate window), otherwise "Unknown player" (still allowed);
  - saving never calls OpenDota: ids not in the pool or the lookup cache are stored as "Unknown player";
  - names and medals are stored with the listing, so the tab doesn't call OpenDota per view.
- **Typed ids are claims, not links:**
  - a listed id doesn't change `User.player_id`, cards or tags;
  - each player row is labelled "Listed by captain", except the captain's own Steam-verified one, which is "Verified".
- **Unwanted listings:**
  - a logged-in user whose Steam-verified `player_id` is listed on someone else's team can remove themselves (**Not on this team**);
  - the captain is not told who removed it, only that the player list changed;
  - an id may be on more than one team, and the tab and export flag it ("Also listed by another team").
- **Who sees what:**
  - logged-out visitors see team names, player names and medals, open roles, the note and full/partial;
  - **contact details show only to logged-in users** and in the admin export, so they can't be scraped anonymously.
- **Fair promotion:**
  - partial teams are shown in a **shuffled order that changes once a day**, seeded by the period and the date, so the first to sign up isn't always first and editing a listing doesn't bump it;
  - filters narrow the list (players needed, open role, any medal range), and nothing is ranked by skill;
  - full teams move to a collapsed **Full teams** section at the end;
  - **Layout: card grid** (canvas option A, chosen 2026-11-10): one same-size `.panel` card per team, with players needed as the one large number, open slots drawn as rows, and the contact in the card footer. The compact table (B) is the fallback if signups pass about 30 teams; "Fits us" (C) is left out of this version.
- **No in-app merging:** teams reach each other through the contact detail. Joining or merging teams in the app is out of scope.
- **Organiser data:**
  - Admin › Settings › Season › Team signup lists every listing (including full ones) and can remove one (audited);
  - **Download CSV** gives one row per player: period, team, captain username, contact, full, open roles, note, Dota id, name, medal, verified, also on another team, updated at;
  - a JSON form of the same data is available to admins.
- **Retention:**
  - listings, contacts and players are deleted 60 days after their period closes (daily cleanup) or when an admin clears the period;
  - a user deleting their listing deletes it at once;
  - the privacy page says what is stored and for how long.
- **Data:** three new tables (no migration): `team_signup_periods`, `team_signups` and `team_signup_players`. Listings don't reference `teams` or `players` by foreign key, since a season Reset deletes those.
- **Code layout:**
  - `backend/team_signup.py` holds the logic;
  - `backend/routers/team_signup.py` holds the public and captain routes, and `backend/routers/admin_team_signup.py` the admin ones;
  - the OpenDota name lookup moves from `routers/admin_players.py` to `backend/player_lookup.py`, used by both.

Resolves GitHub issue #220.

## User Stories

### An Admin Opens and Closes the Signup Period
**User story**
As an admin, I want to open a team signup period before the season and close it when signups end, so that the Team Finder tab is shown only when teams are forming.

**Acceptance criteria**
- **Open:** Admin › Settings › Season has a Team signup section. **Open signup** takes a label (required, up to 40 characters) and an optional closing time, and is refused with `409` while another period is open.
- **Visible:** while a period is open and its closing time hasn't passed, `GET /config` returns `team_signup_open: true` and the Team Finder tab shows for everyone. Admins see the tab at any time.
- **Close:** **Close now** ends the period at once. A period whose closing time has passed is closed without a background job. Once it is closed, `GET /config` returns `false`, the tab hides for non-admins, and saves are refused with `409`.
- **Audit:** opening, closing, clearing and removing a listing are recorded in the audit log with the admin's name and the period label.
- **Refused:** non-admins get `403` from every `/admin/team-signup` route.

### A Captain Lists a Partial Team
**User story**
As a team captain, I want to list my team with the players I have, the roles we still need and how to reach me, so that other partial teams and players can find us.

**Acceptance criteria**
- **Who:** a logged-in website account can create one listing per open period. Logged-out visitors see "Log in to list your team". Twitch soft accounts have no website session, so their requests are refused as logged out (`401`); the listing logic also refuses a soft account (`403`) as a defensive check.
- **Fields:** team name (2–32 characters, cleaned, no links), 1–7 Dota ids, open roles from positions 1–5 (optional), a note (up to 280 characters, no links, optional), and contact (required, up to 100 characters).
- **Ids:**
  - a 32-bit Dota id or a Steam64 id (converted) is accepted;
  - the form shows each id's name and medal from the pool or OpenDota before saving, or "Unknown player";
  - a duplicate id in the same listing, or more than 7 ids, is refused (`422`).
- **Own player:** when the captain's account has a Steam-verified player, it is added first and labelled Verified.
- **Edit and delete:** the captain can change any field or delete the listing while the period is open. Deleting removes the listing and its contact at once.
- **Full:** the captain can mark the team full and undo it. A full team moves to the Full teams section.
- **Limits:** saves are rate-limited per user, and closed periods refuse saves (`409`).

### Captains Browse the Other Teams
**User story**
As a captain or player looking for a team, I want to browse the listed teams and their players fairly, so that I can find a team that fits and contact its captain.

**Acceptance criteria**
- **List:** the Team Finder tab lists partial teams with their name, players (name, medal, Verified or Listed by captain), open roles, players needed (5 minus listed players, at least 0), the note and the last update date.
- **Order:** partial teams are shuffled in an order that stays the same for a day and changes the next (seeded by period and date), and editing a listing doesn't move it up. Full teams are in a collapsed Full teams section at the end.
- **Filters:** players needed, open role and medal range narrow the list in the browser.
- **Contact:** logged-in users see each team's contact. Logged-out visitors see "Log in to see contact details", and `GET /team-signup` leaves contacts out for them.
- **Duplicates:** a player listed on more than one team is marked "Also listed by another team".
- **Escaping:** every user-written field is escaped in the page.

### A Player Removes Themselves From a Team
**User story**
As a player, I want to remove myself from a team that listed me without asking, so that my name isn't used without my consent.

**Acceptance criteria**
- **Who:** a logged-in user whose Steam-verified player is listed on another captain's team sees **Not on this team** on that player row.
- **Effect:** the player row is deleted, and the listing shows the change. The captain isn't told who removed it, and an audit row records the removal.
- **Refused:** a user without that verified player gets `403`, and a captain removing their own player uses the edit form instead.
- **Re-adding:** the captain can list the id again, and the player can remove it again.

### The Organiser Exports the Signups
**User story**
As the tournament organiser, I want the signups as a spreadsheet, so that I can contact captains and plan the divisions without copying data by hand.

**Acceptance criteria**
- **Download:** Admin › Settings › Season › Team signup has **Download CSV** for the current or last period. It has one row per player, with the columns period, team, captain username, contact, full, open roles, note, Dota id, name, medal, verified, also on another team and updated at.
- **Safe for spreadsheets:** a cell starting with `=`, `+`, `-`, `@`, a tab or a carriage return is prefixed with `'`, so it can't run as a formula.
- **Admin list:** the section lists every listing with player counts and a **Remove** button (audited).
- **Retention:** listings are deleted 60 days after their period closes, or at once with **Clear signups** (audited, with confirmation). The privacy page describes the data and the 60 days.

## Implementation

### Critical Files
| File | Change |
|---|---|
| `design/ui_kits/fantasy_web/team-finder.html` (new) | Step 1 canvas: layout and ordering options for the Team Finder tab |
| `backend/models.py` | `TeamSignupPeriod`, `TeamSignup`, `TeamSignupPlayer` (new tables, no migration) |
| `backend/player_lookup.py` (new) | Id parsing (32-bit or Steam64), the OpenDota name and medal lookup with its cache, moved from `routers/admin_players.py` |
| `backend/routers/admin_players.py` | Use `player_lookup` (behaviour unchanged) |
| `backend/team_signup.py` (new) | Period state, listing validation, daily shuffle, duplicates, CSV rows, retention cleanup |
| `backend/routers/team_signup.py` (new) | Public, captain and player routes |
| `backend/routers/admin_team_signup.py` (new) | Period, listing removal, export and clear routes |
| `backend/main.py` | Mount the routers; `team_signup_open` in `GET /config`; add the cleanup to the daily task |
| `frontend/index.html`, `frontend/app-team-finder.js` (new), `frontend/style.css` | Team Finder tab and the captain form |
| `frontend/app-admin-season.js` | Team signup section in Admin › Settings › Season |
| `frontend/privacy.html` | Team signup data and retention |
| `markdown/ui_description/team-finder.md` (new), `markdown/ui_description/admin.md` | Tab specs |
| `markdown/features/core/team-signup.md` | Feature doc |
| `backend/tests/test_issue_220_pre_season_team_signup.py` | Tests |

No migration (new tables only), no new env var. The 60-day retention, the field limits and the rate limit are module constants.

### Step 1 — Design canvas (`/ui-design`)
Before the frontend work, make a standalone prototype at `design/ui_kits/fantasy_web/team-finder.html` with the design system's tokens and fonts and sample data (eight partial teams, two full, a duplicate player, a team of one). It compares:
- **Layouts:**
  - a card grid, one `.panel` per team with player rows;
  - a compact table with expandable rows;
  - a "fits us" view that ranks by open roles matching the viewer's own.
- **Ordering:**
  - the daily shuffle;
  - most players needed first;
  - recently updated.
  Each option notes its fairness trade-offs.
- **The captain form,** including the id lookup states (looking up, found, unknown, invalid) and the Full toggle.

**Done** (`design/ui_kits/fantasy_web/team-finder.html`). The owner chose the **card grid** (option A) with the **daily shuffle**. Step 5 builds that layout; the canvas is the visual reference for cards, player rows, badges, filters, the Full teams section and the captain form. The captain's create, update and delete flow is drawn in the canvas and in the feature doc (Captain flow).

### Step 2 — Models
```
TeamSignupPeriod: id, label, opened_at, closes_at (nullable), closed_at (nullable), opened_by_user_id
TeamSignup: id, period_id → team_signup_periods, captain_user_id → users, team_name, contact, note,
            open_roles_json, is_full, created_at, updated_at
            unique (period_id, captain_user_id)
TeamSignupPlayer: id, signup_id → team_signups, account_id (32-bit Dota id), name, rank_tier,
                  leaderboard_rank, verified, added_at
                  unique (signup_id, account_id)
```
At most one open period is enforced in the open route inside the transaction (a partial unique index on `closed_at IS NULL` as in `twitch_mvp_polls`).

### Step 3 — Shared player lookup
Move `_parse_lookup_ids`, `_opendota_name` and the cache from `routers/admin_players.py` to `backend/player_lookup.py`. Accept a Steam64 id (17 digits from `76561197960265728`) and convert it to the 32-bit id. Return the medal from the pool's `rank_tier` or from the OpenDota response (`player_rank.parse_rank`). The admin route keeps its responses, and its existing tests stay green.

### Step 4 — Routes
```
GET    /team-signup                      public     → period, listings (contacts only when logged in), own listing
GET    /team-signup/lookup?ids=…         logged in, period open (409 otherwise) → names and medals for typed ids (rate-limited, OpenDota budget-capped)
PUT    /team-signup/mine                 logged in  {team_name, players[], open_roles[], note, contact, is_full}
DELETE /team-signup/mine                 logged in
POST   /team-signup/{id}/not-on-team     logged in, Steam-verified player on that listing

GET    /admin/team-signup                admin      → periods and every listing
POST   /admin/team-signup/period         admin      {label, closes_at?}
POST   /admin/team-signup/period/close   admin
DELETE /admin/team-signup/{id}           admin
GET    /admin/team-signup/export.csv     admin      ?period_id=
POST   /admin/team-signup/clear          admin      {period_id} (recent re-auth, as other destructive admin actions)
```
State-changing routes use the existing Origin check and session rules. Saves and lookups are limited per user, and `GET /team-signup` per IP. Responses are dicts and never include user ids or emails. Captains are shown by team name only, with their username only in the admin export.

### Step 5 — Frontend
- **Tab:** the Team Finder tab button is hidden unless `team_signup_open` (or the viewer is an admin). Partial teams show as a card grid (`repeat(auto-fit, minmax(320px, 1fr))`, one column at phone width) in the daily shuffle order, as in the canvas. At phone width a player's badges move under the name and medal.
- **Captain form:** an id field with a live lookup (debounced, batched), player rows with medal and Verified / Listed by captain, open-role checkboxes, note, contact and the Full toggle, then Save and Delete. It shows "Signup closed" when the period ends mid-edit.
- **Admin › Settings › Season › Team signup:** period status, Open signup / Close now, the listings table with Remove, Download CSV and Clear signups.
- **Escaping:** every user-written string goes through the shared escape helper or `textContent`.

### Step 6 — Retention, privacy and docs
- **Daily cleanup:** deletes periods closed over 60 days ago, with their listings and players.
- **Privacy page:** what a listing stores, who sees the contact, the 60 days and deletion.
- **Docs:** `markdown/ui_description/team-finder.md`; the How to Play tab gets a short Team Finder paragraph under Players; the feature doc is filled in.

### Step 7 — Tests
- **Period:** open, one open at a time, close now, lazy close at `closes_at`, `/config` flag, admin-only routes, audit rows.
- **Listing:**
  - field limits and cleaning, link refusal, 1–7 unique ids, Steam64 conversion;
  - the captain's verified player added first;
  - one listing per account per period, soft accounts refused, closed period refused, delete, Full toggle.
- **Browse:** contacts only for logged-in users; the daily order stable within a day, changing the next, and unaffected by edits; full teams last; duplicate flags; no user ids or emails in responses.
- **Not on this team:** only the matching verified player; the row is deleted; audited.
- **Export:** columns, one row per player, formula-injection prefixing.
- **Retention:** cleanup after 60 days; Clear signups.
- **Lookup refactor:** the admin lookup tests unchanged; the captain lookup rate-limited, capped per user and in total, non-blocking when the OpenDota window is full, refused without an open period; saves make no OpenDota call; OpenDota names cleaned.

## Verification
- **End to end on a local instance:**
  1. As admin, open a period "Season 17" with a closing time.
  2. As two users, list a partial team each: one with Steam linked, one with a Steam64 id typed in.
  3. Browse logged out and logged in, and check that contacts show only when logged in.
  4. Mark one team full and check that it moves to Full teams.
  5. As a third user with Steam linked, remove yourself from a team that listed your id.
  6. Download the CSV and open it in a spreadsheet.
  7. Close the period and check that the tab hides and saves are refused.
- **Edge cases:**
  - an OpenDota outage during lookup gives "Unknown player" and the save still works;
  - a team name with a link is refused;
  - a contact starting with `=` is exported as text;
  - the same id is listed on two teams;
  - a period's closing time passes while a captain is editing;
  - Reset (season) leaves the listings intact.
- **Before release:** a security change review (new routes with user input and personal data), and `/ux-reviewer team-finder` after the frontend lands.
