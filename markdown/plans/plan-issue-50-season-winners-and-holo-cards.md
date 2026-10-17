# Plan: Season Champions, Accolades and Holo Cards

## Context
Three issues on the S16 End milestone describe one feature: **seasons remember who won and who played**.
- **#50:** keep each season's winners and show them in a History tab.
- **#53:** winners get a visual mark on their card in later seasons. Rautilus suggests a star sticker per season ("S15"), the same system as caster marks, and a **Holo** card base: functionally a Legendary, with a 20 % chance that a winner's Legendary is drawn as Holo.
- **#105:** admins mark season winners from Admin › Player management.

The product owner settled the model on the design canvas (https://claude.ai/artifact/CXUJ4FJ617oaqzAdf54iwr). It has two tiers:
1. **Champions**, 10 players a season: the five players of the team that wins **Div 1** (upper) and the five of the team that wins **Div 2** (lower). Champions get a **Holo card** in every later season they play, plus a **Champion accolade** ("S16 Div 1 Champion").
2. **Accolades**, which add up over seasons and give no Holo:
   - **Most points**, **Best average** and **Best single match**: one player each per season;
   - **Fantasy winner**: a user;
   - **Played**: every player with at least one scored match that season. It shows as a count of seasons, so long-time players stand out in the Players list.

**What the code already does:**
- **Player identity is stable:** `players.id` is the OpenDota account id, so the same person keeps the same id every season.
- **Season Reset wipes the season's data:** it deletes players, teams, matches, stats and **all cards**. It keeps users, tags, the audit log and `season_archive`. The card pruning that the #50 comment asks for therefore already happens. A past champion can only be drawn again if the admin adds them to the new pool.
- **Divisions are not stored on teams:** a team's division only exists per fixture in the schedule feed (`schedule.py`, `div1`/`div2`), and in the league of its matches: each division is its own OpenDota league, and the lower one's name says "Lower" (`League.name`, from OpenDota). The admin picks the winning team of each division; the picker lists that division's teams first (from `matches.league_id`), and the team's players for the season (from `player_match_stats.team_id`) come pre-selected.
- **Season labels from OpenDota** (follow-up): each league is named after its season ("Kanaliiga Season 16", "Kanaliiga Season 16 Lower"). The current season's label comes from the monitored leagues' names; when none names a season (none monitored, "(pending ingest)", or an odd name such as "Kanaliiga"), it is inferred from the archives and accolades. End Season keeps the leagues monitored, so the label stays the ended season until Reset unmonitors them. The End Season dialog prefills it.
- **Cards are created when drawn** (`draw_card`, `draw_booster`). Images are composited on demand by `backend/image.py` from per-rarity templates.

**Decisions** (from the canvas; change them in review if needed):
- **One table for everything:** `season_accolades`, which Season Reset never touches, with names stored in each row.
- **Holo eligibility:** a player with a **champion** accolade in an earlier season. When a Legendary of that player is drawn (normal draw or team booster), it becomes Holo with probability `holo_chance` % (a new admin weight, default 20). Holo is `card_type = "legendary"` plus `cards.is_holo`: scoring, modifiers, roster rules and deck counts are unchanged.
- **Accolade symbols, like a mana cost** (added in review):
  - every kind has its own symbol (icon, colour and plate);
  - **compact form:** one pip per kind in a fixed order, with a number when earned more than once, and the name and seasons on hover, focus or tap. Cards, the Players list and the popup header use it;
  - **expanded form:** one chip per accolade with the full name ("S16 Div 1 Champion"), where space allows: Player management, the popup timeline and History;
  - pips on cards are an HTML overlay, not baked into the image, so they stay hoverable and update without rebuilding images;
  - **Fantasy Winner on cards only through linking** (added in review): it is a user's accolade, so it shows on a player's cards only while the winning user's account has a Steam-verified link to that player (security review: a self-reported player id doesn't count);
  - **Played on cards at low priority** (added in review): it is the last pip, muted, with the seasons count. It is common but still tells how long someone has been around;

  This replaces the earlier stickers capped at three plus "+N". With one pip per kind a player has at most seven, so no cap is needed.
- **No Veteran status** (dropped in review): the seasons-played count is the signal. The Players list shows the count, one bar per recent season (amber for a champion season) and a Titles column.
- **Fantasy winner:** a user, so they also get the existing `season_winner` user tag.
- **Best average minimum:** a player needs at least half as many scored matches as the most-played player (rounded up).
- **Ties:** all tied winners are recorded.
- **Raw points:** award values use raw `fantasy_points` of scored matches.
- **The current season counts as played** live, from this season's stats, before End Season records it.
- **History before S16:** nothing from earlier seasons can be computed, because Reset deleted it. Admins enter S15 by hand:
  - the awards from #50: Glete, Keikari [PV], ImperialZod, Jiri;
  - the S15 champion teams;
  - **Played for S1–S15** with the backfill script, from each season's OpenDota leagues (found by name, "Kanaliiga Season N"; S1–S4 have none), so seasons counts are complete from the start. Seasons it can't reach use the bulk paste.
- **Mark champions favours flexibility** (added in review): it is used about once a season. It works from the active season's teams or, for a past season, from a typed team name and OpenDota ids, and saving replaces that division's set, so corrections are just another save.
- **Holo template:** the Holo art needs `Card_Template_Holo.png` (597 × 845, real transparency). The image on #53 is a 900 × 1273 screenshot with the checkerboard baked in. Until the file is supplied, Holo uses the Legendary template with a generated iridescent sheen.

Resolves GitHub issues #50, #53 and #105.

## User Stories

### Accolades Survive Season Changes
**User story**
As the operator, I want champions and accolades kept in their own record, so that History, accolade symbols, Holo cards and seasons-played counts still work after a season reset.

**Acceptance criteria**
- **New table:** `season_accolades` (created by `create_all`, so no migration is needed) with these columns:
  - `id`, `season_label`;
  - `kind`: `champion`, `most_points`, `best_average`, `best_match`, `fantasy_winner` or `played`;
  - `division` (`div1` or `div2`, for `champion`), `team_name` (denormalised, for `champion`);
  - `player_account_id` and `player_name` (denormalised), or `user_id` and `username` (for `fantasy_winner`);
  - `value`, `match_id` (for `best_match`);
  - `source` (`season_end` or `admin`), `created_at`, `created_by`.
- **No duplicates:** the table is unique on (`season_label`, `kind`, `division`, `player_account_id`, `user_id`).
- **Kept by Reset:** `POST /admin/season/reset` keeps every row, which the response counts and a test both confirm.
- **No dependence on wiped rows:** everything that renders accolades reads names from the row, so it works after players, teams, cards or users are gone or renamed.

### End Season Records Champions and Accolades
**User story**
As an admin ending a season, I want the awards computed, the champions confirmed and everyone's participation recorded in one step, so that nothing is lost at Reset.

**Acceptance criteria**
- **Preview:** `GET /admin/season/accolades-preview` (admin only) returns:
  - the four computed awards (`most_points`, `best_average`, `best_match`, `fantasy_winner`; rules as in Context; ties included);
  - the number of players who will get `played`;
  - the season's teams, each with the players who played for it (`player_match_stats.team_id`), for the champion picker.
- **End Season dialog:**
  - shows the awards and the Played count;
  - prefills the season label with the current season's (from the monitored leagues' OpenDota names), still editable;
  - asks for the **Div 1** and **Div 2** winning teams, each picker listing that division's teams first (from the league of their matches; "Lower" is Div 2), with their players pre-ticked; a stand-in can be unticked, and a player can be added by OpenDota id;
  - then asks for the typed `END SEASON` confirmation.
- **Request body:** `POST /admin/season/end` takes an optional `champions: [{division, team_name, player_account_ids}]`.
- **Saving:** in the same transaction as the archive, it inserts the awards, the champions and one `played` row per player with ≥1 scored match, all with `source = "season_end"`. Each fantasy winner gets the `season_winner` tag.
- **Champions later:** champions are optional at End Season, for when the finals aren't played yet. They can be added later with Mark champions. The dialog then warns "No champions recorded; add them in Player management".
- **Empty season:** with no scored matches, it records no awards and no `played` rows and says so.
- **Audit:** `admin_season_archived` adds `accolades=N champions=M` to its detail.

### Admins Manage Champions and Accolades
**User story**
As an admin, I want to mark champions and add or correct accolades from Player management, so that seasons from before this feature (S15) and mistakes can be fixed.

**Acceptance criteria**
- **Buttons:** Admin › Player management shows **Mark champions** and **Add accolade** next to **Add**.
- **Mark champions** is used about once a season, so it favours flexibility over automation. One form, with two ways to start:
  - **From this season:** pick the season (the current one) and division, then a team from the active season's teams. Its players for the season come pre-filled (`player_match_stats.team_id`), and the admin can change the list.
  - **Past season (backfill):** pick a past season ("Season 1" to the last ended season) and division, type the team name, and add players by OpenDota id. A past champion team may not exist in the current pool at all, or only some of its players may still play, so nothing depends on current teams or players.
- **Roster editor:** both ways end in the same editable list, one row per player with OpenDota id, name and **Remove**. **+ Add player** adds a row; a paste box takes several lines of "`<id> <name>`".
  - **Names:** typing an id fills the name from the pool, else from that player's earlier accolade rows. Otherwise the admin types it. The name stays editable and is stored on the row as given.
  - **No fixed size:** five is usual. Stand-ins or a sixth player are allowed, with a note "6 players (usually 5)".
  - **Validation:** each id is a positive integer and appears once; every row needs a name.
- **Saving replaces the set:** saving writes that season and division's champions as exactly the list shown, in one transaction: new players added, removed ones deleted, names and team name updated. Saving again later with a changed list is how mistakes are fixed.
- **Edit:** **Edit** on a champion row in the table opens the same form for that season and division, already filled in.
- **Endpoint:** `PUT /admin/season-champions` with `{season_label, division, team_name, players: [{account_id, name}]}`; admin plus `require_recent_reauth`; one `admin_champions_set` audit entry with the season, division and added and removed counts. An empty `players` list removes that division's champions.
- **Holo follows the record:** a past-season champion is Holo-eligible from the moment they're recorded, if they are in the pool. A player removed from the list loses eligibility for future draws; cards already drawn as Holo stay Holo.
- **Add accolade:** the form asks for season, kind, and a player (from the pool, or by OpenDota id and name) or a user (for `fantasy_winner`), plus an optional value. For `played` it also accepts several OpenDota ids, one per line, with names.
- **Backfill Played for S1–S15:** the league has 15 completed seasons before this feature. `backend/scripts/backfill_played.py` records them from OpenDota (see *Seasons Played Are Backfilled*); the bulk paste covers any season the script can't reach.
- **Endpoints:**
  - `POST /admin/season-accolades`: one row or a list; admin plus `require_recent_reauth`; validates kind, division and player or user; 409 when a single row is a duplicate (a pasted list skips rows already recorded and reports how many); `admin_accolade_added` audit entry.
  - `GET /admin/season-accolades`: filterable by season and kind.
  - `PATCH /admin/season-accolades/{id}`: value, name, team name; with re-auth and audit.
  - `DELETE /admin/season-accolades/{id}`: with re-auth and an `admin_accolade_removed` audit entry. Removing a `fantasy_winner` doesn't remove a tag already granted.
- **Table:** a "Champions and accolades" table under the pool, with columns Season, Title (chip), Winner, Value, Source, and **Edit** and **Remove**. Champion rows group a season and division into one row ("[Team] · 5 players"), whose **Edit** opens Mark champions filled in, and whose **Remove** removes the whole set after a confirmation.

### Seasons Played Are Backfilled
**User story**
As the operator, I want the 15 seasons played before this feature recorded once, so that the seasons count is right from day one instead of starting at 1 for everyone.

**Acceptance criteria**
- **Script:** `backend/scripts/backfill_played.py [--season "Season 14"] [--league <id> …] [--name-prefix Kanaliiga] [--dry-run]` is a one-off operator tool, like `backfill_bench.py` (#189).
  - **Season from the league names** (follow-up): each division is its own OpenDota league named after its season ("Kanaliiga Season 14", "Kanaliiga Season 14 Lower"), so the script reads each `--league`'s name (`get_league_info`, cached) and derives "Season N". `--season` is optional: when given with leagues it must agree with their names (otherwise an error and nothing written), and it is required only when the names carry no number. Leagues naming different seasons are an error.
  - **Discovery:** `--season "Season 14"` without `--league` finds the leagues in OpenDota's league list (`/leagues`) named "`<prefix>` Season 14", with or without a division suffix (`--name-prefix`, default "Kanaliiga"), and prints what it found. Seasons 1–4 have no numbered OpenDota league; the script says so and points to the bulk paste.
  - It reads each league's match ids (`get_league_matches`), then each match's players. Every `account_id` gets one `played` row for that season, with `source = "admin"`. External data is validated: ids are whole numbers in 1..2^63−1 (not booleans), names are capped at 100 characters, and a match list that isn't a list is a league error.
- **Names:** the current pool name when the player is in the pool, else the match's `personaname`, else "Player <id>".
- **Skips:** anonymous accounts (no `account_id`) are skipped and counted in the report.
- **Safe to rerun:** existing rows are left alone (`INSERT … ON CONFLICT DO NOTHING` on the unique key), and fetched matches are cached in a local file, so an interrupted run resumes without spending its OpenDota quota again. It pauses between calls to stay under the rate limit.
- **Dry run:** `--dry-run` prints per season the matches found, players, new rows and skipped anonymous slots, and writes nothing.
- **Audit:** one `admin_accolade_added` entry per season with `played=N source=backfill`.
- **Fallback:** a season with no OpenDota league (or a missing one) is filled with the Add accolade bulk paste.
- **Operator input:** the script stores no league ids. It finds a season's leagues by name, or takes ids on the command line.

### Cards Show Titles, and Champions' Legendaries Can Be Holo
**User story**
As a player collecting cards, I want past champions' and award winners' cards to show their titles, and champions' Legendaries to sometimes come as Holo, so that a great season leaves a mark in later ones.

**Acceptance criteria**
- **Symbols on cards:** every card (any rarity) shows the player's accolade pips, as in *Accolade Symbols Read at a Glance*. Fantasy Winner appears only when the winning user's account has a Steam-verified link to that player, and Played comes last with the seasons count. The card viewer lists the chips below the card, such as "S16 Div 1 Champion".
- **Holo roll:** when `draw_card` or `draw_booster` creates a Legendary for a player with a `champion` accolade in a season other than the current one, it becomes Holo with probability `holo_chance` % (a `weights` row, default 20, in Scoring config), stored as `cards.is_holo = true` (migration 040).
- **Holo is a Legendary in every rule:**
  - `card_type` stays `legendary`;
  - points, modifiers, roster rules, `GET /deck` and boosters are unchanged;
  - card responses (draw, roster, collection, card detail) add `is_holo`.
- **Holo image:** `Card_Template_Holo.png` when present. Otherwise the Legendary template plus a generated iridescent sheen, with one startup warning.
- **In the UI:** the rarity label reads "Legendary · Holo". The draw reveal adds an iridescent sweep on the card art only, off under reduced motion.
- **Only champions:** a player without a champion accolade never gets a Holo card, and `holo_chance = 0` disables Holo entirely. Award winners who aren't champions get pips but no Holo.

### Accolade Symbols Read at a Glance
**User story**
As a visitor or collector, I want every accolade to have its own symbol, with a number when it was earned more than once, so that a player's record reads at a glance like a mana cost, and I can still find out what each symbol means and when it was earned.

**Acceptance criteria**
- **Symbol set:** each kind has its own Lucide icon, colour token and plate, so symbols differ without relying on colour. Champions sit on a filled plate, awards on an outlined one.

  | Accolade | Name | Icon | Plate | Colour token | On cards |
  |---|---|---|---|---|---|
  | Div 1 champion | Div 1 Champion | `crown` | filled | `--accolade-div1` (gold) | yes |
  | Div 2 champion | Div 2 Champion | `trophy` | filled | `--accolade-div2` (silver) | yes |
  | Most points | Most Points | `flame` | outlined | `--accolade-points` | yes |
  | Best average | Best Average | `gauge` | outlined | `--accolade-average` | yes |
  | Best single match | Best Single Match | `zap` | outlined | `--accolade-match` | yes |
  | Fantasy winner | Fantasy Winner | `medal` | outlined | `--accolade-fantasy` | yes, when the winner's account has a Steam-verified link to the player |
  | Played | Played | `calendar-check` | outlined, muted | `--accolade-played` (grey) | yes, last; the count is seasons played |
- **Compact form (pips):**
  - one pip per kind the player has earned, in the fixed order of the table, like mana symbols, so the same record always looks the same;
  - a kind earned two or more times shows the count on the pip ("2");
  - kinds not earned are left out, so a player has at most seven pips and no "+N" chip is needed;
  - **Fantasy Winner on a player:** the accolade belongs to a user. It shows on a player's cards and lists only while that user's account has a Steam-verified link (`users.steam_id` and `users.player_id` on a full, non-demo account; a self-reported player id doesn't count). It is resolved when read, so linking adds it and unlinking removes it;
  - **Played is low priority:** it is the last pip, muted grey, and its number is the seasons played (shown even at one). Where a card is too small for the whole column, Played is left out first. Its tooltip compresses runs of seasons: "Played · 12 seasons: S1–S10, S14, S16".
- **Tooltip:** hovering, focusing or tapping a pip shows the name and the seasons, newest first: "Div 1 Champion · S16, S15". Champion tooltips add the team: "S16 with [Team]". The tooltip closes on Escape, on blur or on a tap elsewhere. Each pip carries the same text as its `aria-label` ("Div 1 Champion, 2 times: S16, S15"), so screen readers don't depend on the tooltip.
- **Expanded form (chips):** one chip per earned accolade, with the symbol and the full name: "S16 Div 1 Champion", "S15 Best Single Match". Chips go newest season first, champions first within a season. They wrap onto more lines; where even one chip doesn't fit (a narrow cell or a phone), the view uses the pips instead.
- **Where each form is used:**

  | View | Form |
  |---|---|
  | Cards: card viewer, draw reveal, My Team, collection | pips, on the card |
  | Players tab, Titles column | pips |
  | Player popup | pips in the header; chips in the season timeline |
  | Admin › Player management: pool marker and accolade table | chips (pips at phone width) |
  | History tab | chips in the season panels; pips with counts in the Hall of fame |
- **On the card:**
  - the pips stack down the card's right edge from the top-right corner, beside the art and clear of the name and rarity, read top to bottom like a mana cost (a row across the top would collide with long names);
  - they are sized in em, so they scale with the card, like the card back in issue 205;
  - they are an HTML overlay, not part of the card image, so they stay hoverable, and an accolade added later shows without rebuilding cached images;
  - caster tag stickers stay baked into the image as today.
- **Data:** `GET /accolades` (public) returns, per player:
  - their champion and award accolades: kind, division, short and full season label, team name and value;
  - `fantasy_winner` seasons, only for a player whose winning user has a Steam-verified link now, without the user id or username;
  - the played seasons, including the live season.

  The frontend loads it once per page and uses it for every card.
- **One registry and one renderer:**
  - order, name, icon and token per kind live in one list on each side: `ACCOLADE_KINDS` in `backend/accolades.py` and in `frontend/app-globals.js`, and a test checks the two agree;
  - the shared helpers `accoladePipsHtml(accolades)` and `accoladeChipsHtml(accolades)` render every view; no view builds its own markup.
- **Design system:** the tokens go in `colors_and_type.css` (both copies), and `.accolade-pip`, `.accolade-chip` and the tooltip go in the SHARED STATES section of `style.css`. The README documents the symbol table and the rule "pips for a glance, chips where the names fit".

### Seasons Played and Titles Are Easy to Find
**User story**
As a visitor, I want to see at a glance who has played many seasons and who has won what, so that the league's history is visible where players are listed.

**Acceptance criteria**
- **API:** `GET /players` adds per player:
  - `seasons_played`: distinct seasons with a `played` accolade, plus the current season if they have a scored match;
  - `seasons`: those labels;
  - `titles`: champion and award accolades, newest first.
- **Players tab, Seasons column:**
  - the count (tabular numbers);
  - one bar per season for the last six known seasons, grey for played, amber for a champion season, empty for not played;
  - hovering the count lists the seasons.
- **Players tab, Titles column:** the accolade pips, sortable by the number of titles.
- **Filters and sorting:** filter chips All, Champions and New this season (first season), and sorting by seasons played, titles or average. There is no Veteran status: the seasons count already shows it.
- **Player popup:** the player popup gains an **Accolades** section, placed in the layout from `plan-issue-208-player-popup-visualizations.md`:
  - a "Holo unlocked" banner for champions;
  - counts (champion titles, season awards, seasons played);
  - the pips in the header;
  - a timeline by season, each season listing its chips, including "S16 Played · 7 matches".
- **History tab:** a top-level **History** tab, after Leaderboards, served by `GET /history/seasons` (public; no user ids).
  - One panel per season, newest first.
  - **Champions:** two team blocks (Div 1 and Div 2) headed by their chip ("S16 Div 1 Champion"), each player with a Holo mark.
  - **Awards:** the four awards as chips, with names and values.
  - **Hall of fame** sidebar: players ranked by titles (champion plus awards, not Played), each with their pips and counts (Played left out).
  - Empty state: "No season history yet."
- **Design system:** every new screen follows it (#202): badges, the self row, data-row grids and tabular numbers.

## Implementation

### Critical Files
| File | Change |
|---|---|
| `backend/models.py` | `SeasonAccolade` model; `Card.is_holo` |
| `backend/migrate.py` | Migration 040: `cards.is_holo BOOLEAN NOT NULL DEFAULT 0` (guarded) |
| `backend/accolades.py` (new) | `compute_awards(db)`, `played_player_ids(db)`, `season_teams(db)`, `record_season(db, label, champions, actor)`, `accolades_for(db, player_ids)`, `holo_eligible(db, player_id)`, `seasons_played(db, player_ids)`, `short_season(label)` |
| `backend/routers/admin_season.py` | Accolades preview; `end_season` records accolades and champions; Reset keeps the table |
| `backend/routers/admin_accolades.py` (new) | `GET`, `POST`, `PATCH` and `DELETE /admin/season-accolades`; `PUT /admin/season-champions` (replace one season and division's champions) |
| `backend/routers/players.py` | `seasons_played`, `seasons` and `titles` on `GET /players` and the player detail |
| `backend/routers/history.py` (new) | `GET /history/seasons`; `GET /accolades` (public pip data: fantasy winner through a current Steam-verified link, played seasons; no user ids) |
| `backend/scripts/backfill_played.py` (new) | One-off Played backfill for S1–S15 from OpenDota league ids |
| `backend/routers/cards.py` | Holo roll in `draw_card` and `draw_booster`; `is_holo` in card responses |
| `backend/image.py` | Holo template with fallback sheen. Accolades are not drawn on the image |
| `backend/seed.py` | `holo_chance` weight (default 20) |
| `frontend/index.html`, `frontend/app-players.js`, `frontend/app-admin-players.js`, `frontend/app-admin-season.js`, `frontend/app-cards.js`, new `frontend/app-history.js`, `frontend/style.css` | Players list columns and filters, popup accolades, admin forms and table, End Season dialog, History tab, Holo label and reveal, pip overlay on cards |
| `frontend/app-globals.js` | `ACCOLADE_KINDS`, `accoladePipsHtml`, `accoladeChipsHtml`, the pip tooltip, and the `GET /accolades` cache |
| `frontend/colors_and_type.css`, `design/colors_and_type.css` | `--accolade-*` colour tokens (kept identical) |
| `.claude/skills/README.md` | The accolade symbol table (icon, plate, colour token), the rule "pips for a glance, chips where the names fit", and the Holo sheen allowed only on card art |
| `assets/Card_Template_Holo.png` | To be supplied |
| `markdown/features/reference/season-lifecycle.md`, `card-image-generation.md`, `markdown/features/core/cards.md`, `admin-player-pool.md`, `markdown/ui_description/*.md` | Docs |
| `backend/tests/test_issue_50_season_winners_and_holo_cards.py` | Tests |

No new env var.

### Step 1 — Model and helpers
Add `SeasonAccolade`, `Card.is_holo` with migration 040, and `accolades.py`.

### Step 2 — End Season and Reset
- **End Season:** add the preview endpoint and the champion picker data. `end_season` records awards, champions and `played` rows atomically, and grants the fantasy winner tag.
- **Reset:** keeps the table.

### Step 3 — Admin management
Add the endpoints, Mark champions (this season or past season, the roster editor, edit by saving again), Add accolade (including the bulk Played paste), the table, and the pool marker.

### Step 4 — Cards
Add the Holo roll in both draw paths, `is_holo` in responses, the Holo template and sheen in the image, and the pip overlay on every card view.

### Step 5 — Players, popup and History
Add the `GET /players` fields, the Players tab columns and filters, the popup Accolades section, `GET /history/seasons` and the History tab.

### Step 6 — Design system
Add `ACCOLADE_KINDS` on both sides, the `--accolade-*` tokens, `.accolade-pip`, `.accolade-chip` and the tooltip in the shared-states section, `accoladePipsHtml` and `accoladeChipsHtml`, `GET /accolades`, and the README symbol table. Do this before Steps 3–5 use the symbols. `/ui-design` checks the pip position on the card template and the symbol contrast on each rarity.

### Step 7 — Seed S15 and backfill Played (after deploy, by hand)
With Add accolade and Mark champions, the admin enters the S15 awards (Glete: most points; Keikari [PV]: best average; ImperialZod: best single match; Jiri: fantasy winner). They also enter the Div 1 and Div 2 champion teams for S15 and any earlier seasons they know, using Mark champions › Past season. Then, after `bash scripts/backup-db.sh`, they run `backend/scripts/backfill_played.py --season "Season N" --dry-run` per season (S5–S15): it finds that season's leagues by name and labels the rows from them; then the same without `--dry-run`. S1–S4 have no numbered OpenDota league, so they use the Add accolade Played paste.

### Step 8 — Docs and tests
**Docs:** the season lifecycle, card image generation, the Holo rule in cards, the admin player pool, the UI descriptions and the design system.

**Tests:**
- **Computation:**
  - awards, the average minimum and ties;
  - Played is recorded for every player with a scored match and for no one else;
  - End Season is atomic, with and without champions;
  - Reset keeps the table.
- **Admin endpoints:**
  - re-auth, 409 on a duplicate, validation;
  - bulk Played;
  - `PUT /admin/season-champions`: replaces the set (adds, removes, renames in one save), a past season with players not in the pool, duplicate or invalid ids rejected, an empty list clears it, re-auth and audit counts;
  - Holo eligibility follows the champion set: a removed player is no longer eligible, an existing Holo card stays;
  - backfill script: dry run writes nothing, rerun adds nothing, anonymous accounts skipped, names from pool then match, cached matches not refetched (OpenDota mocked);
  - audit entries.
- **Holo:**
  - champion with a mocked roll → Holo;
  - an award winner who isn't a champion → never;
  - `holo_chance = 0` → never;
  - boosters too;
  - scored like a Legendary.
- **Symbols:**
  - pips group by kind in the fixed order, with the count shown only from two;
  - tooltip and `aria-label` text name the kind and the seasons, newest first, with the team for champions;
  - chips are one per accolade, with the full name ("S16 Div 1 Champion");
  - Fantasy Winner pip only while the winner has a Steam-verified link to the player (none for a self-reported id), gone after unlinking; `GET /accolades` has no user ids or usernames;
  - Played is the last pip, its count is seasons played including the live season, and the tooltip compresses runs ("S1–S10, S14");
  - the backend and frontend `ACCOLADE_KINDS` agree;
  - no view builds pip or chip markup outside the shared helpers.
- **`GET /players`:** seasons count includes the live season; titles.
- **History:** order, ties, no user ids.
- **Migration:** coverage passes.

## Verification
- **End Season:** on a test copy, End Season shows the awards and the Played count, and the champion picker pre-ticks the winning teams' players. After Reset, History, the Players counts (once the players are re-added) and the accolade table still hold everything.
- **Holo:** with `holo_chance` at 100 on test, a past champion's Legendary draw is Holo with its crown pip. A best-match winner who wasn't a champion gets a pip and no Holo.
- **Players tab:** the seasons count and bars match the backfill; the Champions and New this season filters work; no Veteran badge or filter.
- **Symbols:** a two-time champion's card shows a crown pip with "2". Hovering, tabbing to or tapping it shows "Div 1 Champion · S16, S15". Player management and History show "S16 Div 1 Champion" chips, which turn into pips at phone width.
- **Missing template:** Holo cards use the fallback sheen, with one log warning.
- **Deploy:** includes migration 040, so run `bash scripts/backup-db.sh` first.
- **Backfill:** a dry run for one past season lists plausible counts; the real run then shows those seasons in the Players counts, and a rerun adds nothing.
- **Fantasy Winner pip:** link a test account that has a fantasy win to a player and the medal appears on that player's cards; unlink and it's gone.
