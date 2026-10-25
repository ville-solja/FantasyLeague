# Season Champions, Accolades and Holo Cards

Issues #50, #53 and #105. Plan: `markdown/plans/plan-issue-50-season-winners-and-holo-cards.md`. Design canvas: https://claude.ai/artifact/CXUJ4FJ617oaqzAdf54iwr.

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
- **Roster editor:** both ways end in the same editable list, one row per player with OpenDota id, name and **Remove**. **+ Add player** adds a row. *(Superseded by #214: the paste box for "`<id> <name>`" lines was removed; see `admin.md`, Admin Enhancements.)*
  - **Names:** typing an id fills the name from the pool, else from that player's earlier accolade rows. Otherwise the admin types it. The name stays editable and is stored on the row as given.
  - **No fixed size:** five is usual. Stand-ins or a sixth player are allowed, with a note "6 players (usually 5)".
  - **Validation:** each id is a positive integer and appears once; every row needs a name.
- **Saving replaces the set:** saving writes that season and division's champions as exactly the list shown, in one transaction: new players added, removed ones deleted, names and team name updated. Saving again later with a changed list is how mistakes are fixed.
- **Edit:** **Edit** on a champion row in the table opens the same form for that season and division, already filled in.
- **Endpoint:** `PUT /admin/season-champions` with `{season_label, division, team_name, players: [{account_id, name}]}`; admin plus `require_recent_reauth`; one `admin_champions_set` audit entry with the season, division and added and removed counts. An empty `players` list removes that division's champions.
- **Holo follows the record:** a past-season champion is Holo-eligible from the moment they're recorded, if they are in the pool. A player removed from the list loses eligibility for future draws; cards already drawn as Holo stay Holo.
- **Add accolade:** the form asks for season, kind, and a player (from the pool, or by OpenDota id and name) or a user (for `fantasy_winner`), plus an optional value. For `played` it also accepts several OpenDota ids, one per line, with names.
- **Backfill Played for past seasons:** the league has 15 completed seasons before this feature. `backend/scripts/backfill_played.py` records S4–S15 from OpenDota (see *Seasons Played Are Backfilled* and #212's `--all`); the bulk paste covers S1–S3 and any season the script can't reach.
- **Endpoints:**
  - `POST /admin/season-accolades`: one row or a list; admin plus `require_recent_reauth`; validates kind, division and player or user; 409 when a single row is a duplicate (a pasted list skips rows already recorded and reports how many); `admin_accolade_added` audit entry.
  - `GET /admin/season-accolades`: filterable by season and kind.
  - `PATCH /admin/season-accolades/{id}`: value, name, team name; with re-auth and audit.
  - `DELETE /admin/season-accolades/{id}`: with re-auth and an `admin_accolade_removed` audit entry. Removing a `fantasy_winner` doesn't remove a tag already granted.
- **Table:** a "Champions and accolades" table under the pool, with columns Season, Title (chip), Winner, Value, Source, and **Edit** and **Remove**. Champion rows group a season and division into one row ("[Team] · 5 players"), whose **Edit** opens Mark champions filled in, and whose **Remove** removes the whole set after a confirmation.

### Seasons Played Are Backfilled
*(Extended by #212: league ids now live in `backend/scripts/kanaliiga_leagues.json`, Season 4 is covered through it, and `--all` / `--max-calls` run every past season in one command. See* Season Participation Backfill *below.)*

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
- **Symbols on cards:** every card (any rarity) shows the player's accolade pips, as in *Accolade Symbols Read at a Glance*. Fantasy Winner appears only when the winning user's account has a Steam-verified link to that player, and Played comes last with the seasons count. The card viewer lists the chips below the card, such as "S16 Div 1 Champion". *(Superseded by #228: no card face shows pips; the card viewer lists the accolades with their details in an Accolades section.)*
- **Holo roll:** when `draw_card` or `draw_booster` creates a Legendary for a player with a `champion` accolade in a season other than the current one, it becomes Holo with probability `holo_chance` % (a `weights` row, default 20, in Scoring config), stored as `cards.is_holo = true` (migration 040).
- **Holo is a Legendary in every rule:**
  - `card_type` stays `legendary`;
  - points, modifiers, roster rules, `GET /deck` and boosters are unchanged;
  - card responses (draw, roster, collection, card detail) add `is_holo`.
- **Holo image:** `Card_Template_Holo.png` when present (the repo ships none since #228). Otherwise the Legendary template plus a generated iridescent sheen, with one startup warning.
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
  | Cards: card viewer, draw reveal, My Team, collection | pips, on the card (since #228: none on the card; detail lines in the card viewer's Accolades section) |
  | Players tab, Titles column | pips |
  | Player popup | pips in the header; chips in the season timeline |
  | Admin › Player management: pool marker and accolade table | chips (pips at phone width) |
  | History tab | chips in the season panels; pips with counts in the Hall of fame |
- **On the card** *(superseded by #228: the pips left the card face)*:
  - the pips stack down the card's right edge from the top-right corner, beside the art and clear of the name and rarity, read top to bottom like a mana cost (a row across the top would collide with long names);
  - they are sized in em, so they scale with the card, like the card back in issue 205;
  - they are an HTML overlay, not part of the card image, so they stay hoverable, and an accolade added later shows without rebuilding cached images;
  - caster tag stickers stay baked into the image as today (superseded by #217: tags are symbols on the card's left edge).
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

## Season Participation Backfill (issue #212)

Plan: `markdown/plans/plan-issue-212-season-participation-backfill.md`. Feature doc: `markdown/features/reference/season-participation-backfill.md`.

### Past Seasons' Participation Is Backfilled in One Run
**User story**
As the operator, I want one command that records who played in every past Kanaliiga season found on OpenDota, so that seasons-played counts are right without ingesting old matches.

**Acceptance criteria**
- **League file:** `backend/scripts/kanaliiga_leagues.json` lists seasons 4–16 with their league ids and a note per season (empty Lower leagues, the unnumbered S4 league). A test checks it is valid: unique ids, seasons ascending, each league an int.
- **`--all`:** runs every listed season except the live one (`accolades.current_season_label`), oldest first, using the same per-season code as `--season`. Each season writes its own `admin_accolade_added` audit entry (`played=N source=backfill`).
  - `--dry-run --all` writes nothing.
  - A second run adds nothing.
- **`--max-calls N` (default 900):** caps OpenDota calls per run. When it's reached, the run stops after the current match, keeps the cache, records what it finished, and exits 2 with "Budget used: resume to continue from Season N". A resumed run spends no calls on cached matches.
- **Unreadable matches:** a match that can't be fetched after the client's retries is counted in the report and retried on the next run. The season's rows are still written for the matches that were read.
- **Report:** the run prints a per-season line (players, new rows, already recorded, unreadable matches), the totals, and the seasons-per-player distribution.
- **Existing modes unchanged:** `--season` and `--league` work as before. S4 resolves through the file even though its OpenDota name has no number.

### Counts Say Where They Start
**User story**
As a visitor, I want the seasons count to say it starts at Season 4, so that a long-time player's number isn't mistaken for their whole history.

**Acceptance criteria**
- **Players tab:** the Seasons legend reads "Seasons played since Season 4 (earlier seasons have no OpenDota record)".
- **Hover text:** the count's hover text lists the seasons and ends with "Counted from Season 4".
- **One constant:** the first counted season is a single constant used by the backend (`/players` response field `seasons_counted_from`) and the frontend. The text isn't hard-coded in two places.
