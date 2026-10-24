# Plan: Admin Enhancements

## Context
The Admin tab grew one panel at a time, and the most frequent jobs are now the hardest to do. Approving a streamer, setting a missing MVP and adding a player are the most common tasks, but:
- **Streamer approvals:** they sit at the bottom of User Management.
- **Matches table:** it is ordered by data columns, not by the MVP job.
- **Id fields:** they are number inputs with +1/−1 spinners, which make no sense for 6–10 digit ids.
- **Settings:** a two-column pile of twelve unrelated panels.

**What the code does today:**
- **Admin tabs** (`frontend/index.html`, `#admin-tab-bar`): User Management, Week Management, Player Management, Matches, Audit Log, Settings.
  - User Management holds the users table, then Twitch collection merges, Twitch status, **Approved streamers** (#175) and Superseded player id claims.
- **Add player** (`#addPlayerModal`): a single `type="number"` input. `POST /admin/players` fetches the name from OpenDota only on save (`routers/admin_players.py`), so the admin sees the name after it is added.
- **Bulk add** (`#bulkAddPlayersModal`): comma-separated ids in a text input, with no preview of who will be added.
- **Mark champions** (`#markChampionsModal`, #50): a roster editor plus a paste box. The name column is cramped by the modal width.
- **Add accolade** (`#addAccoladeModal`): `type="number"` OpenDota id and value inputs.
- **Matches** (`app-admin-matches.js`, `GET /admin/matches`):
  - 14 columns: Match, League (raw id), Team 1, Team 2 (radiant/dire order), Start, three timing columns, Parse, Scoring, Week, MVP, VOD, Set MVP;
  - one filter (Unparseable);
  - the scoring checkboxes don't line up;
  - Team 1 and Team 2 swap between games of a series, because they follow radiant/dire.
- **Schedule feed:** `schedule.get_schedule` already knows each series' games (`series_result.match_ids`), its division (div1/div2 lists), its teams in feed order and its `stream_url`. The league name gives the division (`accolades.league_division`, #50).
- **Settings:** League Management, Tag Definitions, Promo Codes, Scoring Weights, Notifications, Token Grant Events, Refresh Schedule Cache, Recalculate, Re-enrich Profiles, Season Lifecycle, Database Backups and Demo Mode, in two columns in the order they were added.

**Decisions** (change them in review if needed):
- **New Twitch sub-tab:** after User Management. **Approved streamers** sits at its top (waiting approvals first), then Twitch status, then Twitch collection merges.
  - The sub-tab button and the top-level Admin tab show a count badge of pending approvals. The count comes from the existing channels endpoint and is fetched when an admin loads the page.
  - Notifying admins outside the site (email, Discord or Twitch chat) is **split off** into #215, as the issue suggests.
- **Superseded player id claims** stays in User Management: it is account history.
- **No spinners on ids:** every OpenDota id input becomes `type="text" inputmode="numeric"` with a digits-only pattern. That covers Add player, Bulk add, Mark champions, Add accolade and End Season's add-by-id. Accolade *value* uses `inputmode="decimal"`, also with no spinner. The design README gets the rule "ids are text, not numbers".
- **Name preview:** a new admin endpoint, `GET /admin/players/lookup?ids=…`, gives each id's name.
  - Lookup order: the pool name, else the OpenDota `personaname`, else "not found".
  - At most 50 ids per call, admin only, with a short in-process cache so retyping doesn't spend OpenDota quota.
  - **Add player** looks up the name when the field loses focus (or on Enter) and shows "Glete · not in the pool". The name is a preview; saving works as today.
  - **Bulk add** shows a preview list (id, name, and new / already in pool / not found) before Confirm, and only new ids are submitted.
- **Mark champions:** the paste box goes. The modal widens to the roster's needs, and each roster row puts the id and the name on one line, with the name field getting the remaining width. At phone width the row stacks.
- **Matches is rebuilt around the MVP job:**
  - **Rows group by series:** a series header row (Team A vs Team B · Div 1 · week · stream link), with its games below.
  - **Teams in feed order:** the series' team 1 and team 2, so they don't swap between games. Unscheduled matches are listed under "Not in the schedule".
  - **Column order:** Match id (link) · Team 1 vs Team 2 · League (name and Div) · Start · MVP (name and **Set MVP**) · Stream · then the rest (week, scoring, parse, timings).
  - **Filters:** MVP missing (on by default when any are missing), League (All, Div 1, Div 2) and Unparseable.
  - **VOD → stream:** the VOD column becomes the series' **Stream** link from the schedule feed. The admin VOD link (`matches.vod_url`), which the Weekly Report shows, moves into the row's **More** details, so nothing is lost.
  - **Scoring checkboxes** sit in a fixed grid so they line up.
  - `GET /admin/matches` adds per match: `series_key`, `series_team1_id`, `series_team2_id`, `division`, `league_name` and `stream_url`, from one `get_schedule` pass.
- **Settings is regrouped** (canvas below) into six sections with a section nav:
  1. **Season:** League Management, Season Lifecycle, Refresh Schedule Cache.
  2. **Scoring:** Scoring Weights, Recalculate Fantasy Points.
  3. **Tokens and rewards:** Promo Codes, Token Grant Events.
  4. **Announcements:** Notifications.
  5. **Players and tags:** Tag Definitions, Re-enrich Player Profiles.
  6. **Maintenance:** Database Backups, Demo Mode.

  Every panel gets the same header: title, one-line purpose, primary action on the right. Destructive actions (Reset Season, Recalculate) are styled as danger and sit last in their section. The nav becomes a chip row at phone width. No panel's behaviour changes.
- **Design canvas:** https://claude.ai/artifact/WPnstGBfP24mJeqHFtm6ih (Settings regrouped, Matches by series, Twitch sub-tab).

Resolves GitHub issue #214.

## User Stories

### Streamer Approvals Come First
**User story**
As an admin, I want pending streamer approvals at the top of their own Twitch tab, with a count I can see from anywhere in Admin, so that streamers get approved quickly.

**Acceptance criteria**
- **New sub-tab:** Admin gets a **Twitch** sub-tab after User Management.
- **Order:** Approved streamers first (waiting approvals at the top), then Twitch status, then Twitch collection merges. They move out of User Management; Superseded player id claims stays there.
- **Badge:** when approvals are waiting, the Twitch sub-tab button and the top-level Admin tab button show a badge with the count (for example "2"). The badge has an `aria-label` such as "2 streamers waiting for approval".
  - The count is fetched when an admin loads the page and after each Approve or Reject.
  - With nothing waiting there is no badge.
- **Unchanged:** Approve, Reject and Remove still need the password re-check.
- **Split-off:** notifying admins outside the site is #215.

### Ids Are Typed, and Names Show Before Saving
**User story**
As an admin adding players, I want to type ids without spinner buttons and see the player's name before I save, so that I catch a wrong id immediately.

**Acceptance criteria**
- **No spinners:** OpenDota id inputs in Add player, Bulk add, Mark champions, Add accolade and End Season are `type="text"` with `inputmode="numeric"` and no spinner.
  - Non-digits are rejected with a message.
  - The accolade value uses `inputmode="decimal"`.
- **Lookup endpoint:** `GET /admin/players/lookup?ids=1,2,3` (admin only, at most 50 ids, each a positive integer) returns `[{id, name, source: "pool" | "opendota" | null, in_pool}]`.
  - OpenDota answers are cached in process for 10 minutes.
  - An invalid or oversized request gets 422.
- **Add player:** leaving the id field (or pressing Enter) shows the name and "already in the pool", "not in the pool" or "No OpenDota player with this id". Confirm still adds as today.
- **Bulk add:** after the ids are entered, a preview list shows each id with its name and status (new, already in pool, not found). Confirm adds only the new ids, the count is on the button ("Add 7 players"), and the existing progress panel still runs.

### Mark Champions and Add Accolade Are Simpler
**User story**
As an admin entering champions once a season, I want a plain roster editor where I can read every name, so that the rare task is quick and error-free.

**Acceptance criteria**
- **Mark champions, paste box removed:** the paste box and its parser are removed; **+ Add player** stays.
- **Mark champions, layout:** each roster row shows the id field (fixed width), the name field (the remaining width, never under 12 characters wide) and **Remove** on one line in a modal at least 640 px wide. Below 640 px the row stacks.
- **Add accolade:** no spinner on the id or the value. The bulk Played box stays, because the S1–S15 backfill fallback uses it.

### Matches Are Organised for Setting MVPs
**User story**
As an admin, I want matches grouped by series with the MVP and stream link up front and a filter for missing MVPs, so that I can find and fill missing MVPs fast.

**Acceptance criteria**
- **Grouped by series:** matches group under series headers (teams, division, week, stream link), newest series first. Matches not in the schedule feed are listed under "Not in the schedule".
- **Teams in series order:** games show the series' team 1 and team 2 in the same order in every game, not radiant/dire.
- **Column order:** Match id (OpenDota link), Teams, League (name and Div 1/Div 2), Start, MVP with **Set MVP**, Stream, then Week, Scoring, Parse and the timing columns.
- **Filters** in one row:
  - **MVP missing:** checked by default when any match lacks an MVP;
  - **League:** All, Div 1 or Div 2;
  - **Unparseable:** as today.

  Filters combine. The empty state names the active filters.
- **Stream link:** from the series' `stream_url`, opened in a new tab; "—" when the feed has none. The VOD link editor moves into each match's **More** details. The Weekly Report VOD keeps working.
- **Scoring checkboxes:** aligned in a fixed two-column grid, with labels.
- **API:** `GET /admin/matches` adds `series_key`, `series_team1_id`, `series_team2_id`, `division`, `league_name` and `stream_url` (null when not in the feed). Existing fields are unchanged.

### Settings Grouped by Purpose
**User story**
As an admin, I want Settings grouped into a few named sections with consistent panels, so that I can find a control without scanning twelve boxes.

**Acceptance criteria**
- **Six sections** in this order: Season, Scoring, Tokens and rewards, Announcements, Players and tags, Maintenance, holding the panels listed in Context.
  - A section nav lists them; it is sticky on desktop and a chip row at phone width.
  - Selecting a section scrolls to it, and the last section viewed is remembered per browser.
- **Consistent panels:** every panel has a title, a one-line description and its primary action at the top right.
- **Danger last:** Reset Season and Recalculate are danger-styled and sit last in their sections.
- **No behaviour change:** no panel changes what it does. Every existing element id stays, so existing JS and tests keep working.
- **Matches the canvas:** the layout follows the design canvas.

## Implementation

### Critical Files
| File | Change |
|---|---|
| `frontend/index.html` | Twitch sub-tab and badges; spinner-free id inputs; Add player preview; Bulk add preview list; Mark champions without paste; Matches filters and grouped table; Settings sections and nav |
| `frontend/app-admin.js` | Sub-tab registration, pending-approvals badge, Settings nav |
| `frontend/app-admin-users.js` | Twitch panels render into the new sub-tab; badge refresh after Approve or Reject |
| `frontend/app-admin-players.js` | Lookup on blur, bulk preview, Mark champions paste removal and layout, Add accolade inputs |
| `frontend/app-admin-matches.js` | Series grouping, column order, filters, stream link, VOD in More details, scoring grid |
| `frontend/app-admin-season.js` | End Season add-by-id input |
| `frontend/style.css` | Admin badge, series header rows, scoring grid, roster row layout, Settings nav (tokens only, before GUIDED TOUR) |
| `backend/routers/admin_players.py` | `GET /admin/players/lookup` |
| `backend/routers/admin_matches.py` | Series, division, league name and stream fields from one `schedule.get_schedule` pass |
| `.claude/skills/README.md` | "Ids are text inputs (`inputmode="numeric"`), never number spinners" |
| `markdown/ui_description/admin.md`, `markdown/features/core/admin.md`, `markdown/features/reference/admin-enhancements.md` | Docs |
| `backend/tests/test_issue_214_admin_enhancements.py` | Tests |

No migration, no new env var.

### Step 1 — Twitch sub-tab and badge
Move the three Twitch panels into a new `data-admin-tab="twitch"`. Add the badge (count of channels waiting, from the existing channels endpoint) to the sub-tab button and the Admin tab button.

### Step 2 — Id inputs and lookup
Add `GET /admin/players/lookup`, using the opendota client with the cache. Convert the id inputs. Add the Add player preview and the Bulk add preview list.

### Step 3 — Mark champions and Add accolade
Remove the paste box (`champPaste` and its parser), set the roster row layout and widen the modal. Convert the Add accolade inputs.

### Step 4 — Matches
Extend `GET /admin/matches` with the series fields: map match id → series from `get_schedule`, and the division from the series list or `league_division(league name)`. Rebuild the table around series with the new column order, filters, stream link, More details (VOD and timings) and the scoring grid.

### Step 5 — Settings
Wrap the existing panels in the six sections, add the nav, unify panel headers and style the danger actions. Keep every element id.

### Step 6 — Docs and tests
**Docs:** the admin UI spec, the admin core doc, the feature doc and the design README rule.

**Tests:**
- **Lookup:** admin only; validation (non-numeric, more than 50, empty); pool before OpenDota; cache; not found.
- **`GET /admin/matches`:** the series fields, team order stable across games, null for matches outside the feed.
- **Frontend (source-reading or Node harness):**
  - no `type="number"` on id inputs;
  - the Twitch sub-tab order and badge text;
  - the bulk preview statuses;
  - the Mark champions paste box gone;
  - the matches filters combine;
  - grouping and column order;
  - the Settings sections in order, and all prior element ids still present.

## Verification
- **Twitch:** with a channel waiting, the Admin tab shows a badge, and the Twitch tab lists it first. Approving clears the badge.
- **Add player:** typing an id and tabbing out shows the name. A wrong id says so. Bulk add previews names and adds only new ones.
- **Mark champions:** names are fully readable at desktop width and stack on a phone.
- **Matches:** the MVP-missing filter lists exactly the matches without an MVP. A series' games share team order. The stream link opens the right channel. The VOD editor is under More, and the Weekly Report still shows the VOD.
- **Settings:** every former control is reachable, and the nav jumps to each section.
