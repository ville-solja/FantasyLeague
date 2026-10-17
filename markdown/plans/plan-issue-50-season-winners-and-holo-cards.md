# Plan: Season Champions, Accolades and Holo Cards

## Context
Three issues on the S16 End milestone describe one feature: **seasons remember who won and who played**.
- **#50:** keep each season's winners and show them in a History tab.
- **#53:** winners get a visual mark on their card in later seasons. Rautilus suggests a star sticker per season ("S15"), the same system as caster marks, and a **Holo** card base: functionally a Legendary, with a 20 % chance that a winner's Legendary is drawn as Holo.
- **#105:** admins mark season winners from Admin › Player management.

The product owner settled the model on the design canvas (https://claude.ai/artifact/CXUJ4FJ617oaqzAdf54iwr). It has two tiers:
1. **Champions**, 10 players a season: the five players of the team that wins **Div 1** (upper) and the five of the team that wins **Div 2** (lower). Champions get a **Holo card** in every later season they play, plus a **Champion accolade** ("S16 D1").
2. **Accolades**, which add up over seasons and give no Holo:
   - **Most points**, **Best average** and **Best single match**: one player each per season;
   - **Fantasy winner**: a user;
   - **Played**: every player with at least one scored match that season. It shows as a count, so veterans stand out in the Players list.

**What the code already does:**
- **Player identity is stable:** `players.id` is the OpenDota account id, so the same person keeps the same id every season.
- **Season Reset wipes the season's data:** it deletes players, teams, matches, stats and **all cards**. It keeps users, tags, the audit log and `season_archive`. The card pruning that the #50 comment asks for therefore already happens. A past champion can only be drawn again if the admin adds them to the new pool.
- **Divisions are not stored on teams:** a team's division only exists per fixture in the schedule feed (`schedule.py`, `div1`/`div2`). The admin therefore picks the winning team of each division, and that team's players for the season (from `player_match_stats.team_id`) come pre-selected.
- **Cards are created when drawn** (`draw_card`, `draw_booster`). Images are composited on demand by `backend/image.py` from per-rarity templates.

**Decisions** (from the canvas; change them in review if needed):
- **One table for everything:** `season_accolades`, which Season Reset never touches, with names stored in each row.
- **Holo eligibility:** a player with a **champion** accolade in an earlier season. When a Legendary of that player is drawn (normal draw or team booster), it becomes Holo with probability `holo_chance` % (a new admin weight, default 20). Holo is `card_type = "legendary"` plus `cards.is_holo`: scoring, modifiers, roster rules and deck counts are unchanged.
- **Stickers on cards:**
  - champion accolades first, then the newest awards;
  - at most three, then a "+N" chip;
  - **Played is never a card sticker.**

  The card viewer, player popup and History show everything.
- **Veteran:** 3 or more seasons played. The Players list shows a seasons count, one bar per recent season (amber for a champion season), a Veteran tag and a Titles column.
- **Fantasy winner:** a user, so they also get the existing `season_winner` user tag.
- **Best average minimum:** a player needs at least half as many scored matches as the most-played player (rounded up).
- **Ties:** all tied winners are recorded.
- **Raw points:** award values use raw `fantasy_points` of scored matches.
- **The current season counts as played** live, from this season's stats, before End Season records it.
- **History before S16:** nothing from earlier seasons can be computed, because Reset deleted it. Admins enter S15 by hand:
  - the awards from #50: Glete, Keikari [PV], ImperialZod, Jiri;
  - the S15 champion teams;
  - optionally S15 Played, by pasting OpenDota ids.
- **Holo template:** the Holo art needs `Card_Template_Holo.png` (597 × 845, real transparency). The image on #53 is a 900 × 1273 screenshot with the checkerboard baked in. Until the file is supplied, Holo uses the Legendary template with a generated iridescent sheen.

Resolves GitHub issues #50, #53 and #105.

## User Stories

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

## Implementation

### Critical Files
| File | Change |
|---|---|
| `backend/models.py` | `SeasonAccolade` model; `Card.is_holo` |
| `backend/migrate.py` | Migration 040: `cards.is_holo BOOLEAN NOT NULL DEFAULT 0` (guarded) |
| `backend/accolades.py` (new) | `compute_awards(db)`, `played_player_ids(db)`, `season_teams(db)`, `record_season(db, label, champions, actor)`, `accolades_for(db, player_ids)`, `holo_eligible(db, player_id)`, `seasons_played(db, player_ids)`, `short_season(label)` |
| `backend/routers/admin_season.py` | Accolades preview; `end_season` records accolades and champions; Reset keeps the table |
| `backend/routers/admin_accolades.py` (new) | `GET`, `POST`, `PATCH` and `DELETE /admin/season-accolades` |
| `backend/routers/players.py` | `seasons_played`, `seasons` and `titles` on `GET /players` and the player detail |
| `backend/routers/history.py` (new) | `GET /history/seasons` |
| `backend/routers/cards.py` | Holo roll in `draw_card` and `draw_booster`; `is_holo` in card responses |
| `backend/image.py` | Holo template with fallback sheen; sticker rendering (no Played) |
| `backend/seed.py` | `holo_chance` weight (default 20) |
| `frontend/index.html`, `frontend/app-players.js`, `frontend/app-admin-players.js`, `frontend/app-admin-season.js`, `frontend/app-cards.js`, new `frontend/app-history.js`, `frontend/style.css` | Players list columns and filters, player popup accolades, admin forms and table, End Season dialog, History tab, Holo label and reveal, a sticker helper in the shared-states style |
| `.claude/skills/README.md` | Accolade sticker kinds (icon, colour token), and the Holo sheen allowed only on card art |
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
Add the endpoints, Mark champions, Add accolade (including the bulk Played paste), the table, and the pool marker.

### Step 4 — Cards
Add the Holo roll in both draw paths, `is_holo` in responses, and template, sheen and stickers in the image.

### Step 5 — Players, popup and History
Add the `GET /players` fields, the Players tab columns and filters, the popup Accolades section, `GET /history/seasons` and the History tab.

### Step 6 — Design system
Add the sticker kinds as tokens or classes in the shared-states section, and the README rule.

### Step 7 — Seed S15 (after deploy, by hand)
With Add accolade and Mark champions, the admin enters the S15 awards (Glete: most points; Keikari [PV]: best average; ImperialZod: best single match; Jiri: fantasy winner). They also enter the S15 Div 1 and Div 2 champion teams and, if a roster list exists, S15 Played.

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
  - audit entries.
- **Holo:**
  - champion with a mocked roll → Holo;
  - an award winner who isn't a champion → never;
  - `holo_chance = 0` → never;
  - boosters too;
  - scored like a Legendary.
- **Stickers:**
  - order and the cap of three;
  - Played never on a card.
- **`GET /players`:** seasons count includes the live season; titles.
- **History:** order, ties, no user ids.
- **Migration:** coverage passes.

## Verification
- **End Season:** on a test copy, End Season shows the awards and the Played count, and the champion picker pre-ticks the winning teams' players. After Reset, History, the Players counts (once the players are re-added) and the accolade table still hold everything.
- **Holo:** with `holo_chance` at 100 on test, a past champion's Legendary draw is Holo with its "S16 D1" sticker. A best-match winner who wasn't a champion gets a sticker and no Holo.
- **Players tab:** veterans show the Veteran badge and their season bars; the Veterans and Champions filters work.
- **Missing template:** Holo cards use the fallback sheen, with one log warning.
- **Deploy:** includes migration 040, so run `bash scripts/backup-db.sh` first.
