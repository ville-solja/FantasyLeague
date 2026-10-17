# Season Champions, Accolades and Holo Cards

Issues #50, #53 and #105. Plan: `markdown/plans/plan-issue-50-season-winners-and-holo-cards.md`. Design canvas: https://claude.ai/artifact/CXUJ4FJ617oaqzAdf54iwr.

### Accolades Survive Season Changes
**User story**
As the operator, I want champions and accolades kept in their own record, so that History, stickers, Holo cards and veteran counts still work after a season reset.

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
  - asks for the **Div 1** and **Div 2** winning teams, with their players pre-ticked; a stand-in can be unticked, and a player can be added by OpenDota id;
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
- **Mark champions:** the form asks for season label, division and winning team (from the season's teams, or free text for a past season). The players come pre-ticked from the team, and players can be added by OpenDota id and name. Saving records one `champion` row per player.
- **Add accolade:** the form asks for season, kind, and a player (from the pool, or by OpenDota id and name) or a user (for `fantasy_winner`), plus an optional value. For `played` it also accepts several OpenDota ids, one per line, with names.
- **Endpoints:**
  - `POST /admin/season-accolades`: one row or a list; admin plus `require_recent_reauth`; validates kind, division and player or user; 409 on a duplicate; `admin_accolade_added` audit entry.
  - `GET /admin/season-accolades`: filterable by season and kind.
  - `PATCH /admin/season-accolades/{id}`: value, name, team name; with re-auth and audit.
  - `DELETE /admin/season-accolades/{id}`: with re-auth and an `admin_accolade_removed` audit entry. Removing a `fantasy_winner` doesn't remove a tag already granted.
- **Table:** a "Champions and accolades" table under the pool, with columns Season, Title (sticker), Winner, Value, Source, and **Edit** and **Remove**. Champion rows group a team's five players into one row ("[Team] · 5 players").

### Cards Show Titles, and Champions' Legendaries Can Be Holo
**User story**
As a player collecting cards, I want past champions' and award winners' cards to show their titles, and champions' Legendaries to sometimes come as Holo, so that a great season leaves a mark in later ones.

**Acceptance criteria**
- **Stickers on cards:** every card (any rarity) shows the player's accolade stickers, **excluding `played`**:
  - champion first ("S16 D1"), then awards newest first;
  - at most three, then a "+N" chip;
  - drawn on the card image (`backend/image.py`);
  - the card viewer lists all of them, with reasons such as "S16: Div 1 champion with [Team]".

  Each kind has its own icon and colour, as on the canvas, so they can be told apart without relying on colour alone.
- **Holo roll:** when `draw_card` or `draw_booster` creates a Legendary for a player with a `champion` accolade in a season other than the current one, it becomes Holo with probability `holo_chance` % (a `weights` row, default 20, in Scoring config), stored as `cards.is_holo = true` (migration 040).
- **Holo is a Legendary in every rule:**
  - `card_type` stays `legendary`;
  - points, modifiers, roster rules, `GET /deck` and boosters are unchanged;
  - card responses (draw, roster, collection, card detail) add `is_holo`.
- **Holo image:** `Card_Template_Holo.png` when present. Otherwise the Legendary template plus a generated iridescent sheen, with one startup warning.
- **In the UI:** the rarity label reads "Legendary · Holo". The draw reveal adds an iridescent sweep on the card art only, off under reduced motion.
- **Only champions:** a player without a champion accolade never gets a Holo card, and `holo_chance = 0` disables Holo entirely. Award winners who aren't champions get stickers but no Holo.

### Veterans and Titles Are Easy to Find
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
  - a **Veteran** status badge at 3 or more seasons;
  - hovering the count lists the seasons.
- **Players tab, Titles column:** the stickers, at most three plus "+N".
- **Filters and sorting:** filter chips All, Veterans, Champions and New this season (first season), and sorting by seasons played, titles or average.
- **Player popup:** the player popup gains an **Accolades** section:
  - a "Holo unlocked" banner for champions;
  - counts (champion titles, season awards, seasons played);
  - a timeline by season, each season listing its stickers, including Played with that season's match count.
- **History tab:** a top-level **History** tab, after Leaderboards, served by `GET /history/seasons` (public; no user ids).
  - One panel per season, newest first.
  - **Champions:** two team blocks (Div 1 and Div 2), each player with a Holo mark.
  - **Awards:** the four awards, with names and values.
  - **Hall of fame** sidebar: players ranked by titles (champion plus awards, not Played).
  - Empty state: "No season history yet."
- **Design system:** every new screen follows it (#202): badges, the self row, data-row grids and tabular numbers.
