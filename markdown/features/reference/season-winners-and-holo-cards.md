# Season Champions, Accolades and Holo Cards

Seasons remember who won and who played. Each season has **champions**, the 10 players of the Div 1 and Div 2 winning teams. Champions get Holo cards in later seasons and a Champion accolade. Seasons also hand out **accolades** that add up over time: most points, best average, best single match, fantasy winner and Played (1+ match). Everything sits in a record that Season Reset never touches. It drives the accolade symbols, the Holo roll, seasons-played counts in the Players list, the player popup and the History tab. Resolves GitHub issues #50, #53 and #105; plan: `markdown/plans/plan-issue-50-season-winners-and-holo-cards.md`; design canvas: https://claude.ai/artifact/CXUJ4FJ617oaqzAdf54iwr.

---

## Record

- **Storage:** the `season_accolades` table (`models.SeasonAccolade`): season label, kind (`champion`, `most_points`, `best_average`, `best_match`, `fantasy_winner`, `played`), division and team name for champions, player (OpenDota account id and name) or user (id and username, no foreign key), value, match id (best match), source (`season_end` or `admin`), `created_at`, `created_by`.
- **No duplicates:** the unique index `ux_season_accolades_key` covers season, kind, division, player and user. The nullable parts go through `COALESCE`, because SQLite treats NULLs as distinct in a unique index.
- **Survives Reset:** names are stored on each row, so every reader works after the season's players, teams, cards or users are gone or renamed. `POST /admin/season/reset` keeps the table and reports `kept.season_accolades`.
- **Code:** `backend/accolades.py` holds the logic (`compute_awards`, `played_player_ids`, `season_teams`, `record_season`, `set_champions`, `holo_eligible`, `roll_holo`, `accolades_for`, `player_seasons`, `history`, `short_season`, `current_season_label`).

### The live season's label

`current_season_label(db)` takes it from OpenDota's league names. Each division is its own OpenDota league named after its season ("Kanaliiga Season 16", "Kanaliiga Season 16 Lower"), and `leagues.name` stores that name:
- **From the monitored leagues:** "Season N" is parsed from each monitored league's name (`league_season_number`, case-insensitive, anywhere in the name). If they disagree, the highest wins and a warning is logged. End Season keeps the leagues monitored, so after End Season and before Reset the label is still the season just ended; Reset unmonitors them.
- **Fallback** (no monitored league, a name still "(pending ingest)", or a name without a number such as "Kanaliiga"): after End Season and before Reset (the newest archive is newer than every match) it is the label just archived; otherwise "Season N+1", where N is the highest season number in `season_archive` and in non-champion accolades (champions of the running season can be entered early, so they don't count). With no history at all it is "Season 1".
- Monitoring next season's leagues before Reset would name the new season while the old stats are still there; reset first.

The label is used for the live Played season, the Holo rule ("a season other than the current one") and the Mark champions form.

### Awards

`compute_awards` uses raw `fantasy_points` of scored matches (excluded matches never count):
- **Most points:** highest total. **Best single match:** highest single match, with its match id.
- **Best average:** highest average among players with at least half as many scored matches as the most-played player, rounded up.
- **Fantasy winner:** the top of the season standings (`compute_season_standings`) with more than 0 points.
- **Ties:** every tied winner is listed and recorded.

## End Season

- **Preview:** `GET /admin/season/accolades-preview` returns `season_label`, the four `awards`, `played_count`, `teams` (each with its players from `player_match_stats.team_id`, its `division` and every division it played in, `divisions`) and `champions_recorded` per division for the live season. A team's division comes from the leagues of its matches (`matches.league_id`): `league_division(name)` says `div2` when the league name contains "Lower" (any case), else `div1`; `division` is the one most of its matches were in, null when unknown. `schedule.py` is not involved.
- **Dialog:** Admin › Season Lifecycle › End Season opens a dialog with the season label (prefilled with the current season's label unless one was typed beside the button; editable), the awards, the Played count and a Div 1 and a Div 2 team picker. Each picker lists that division's teams first, then every other team, since a team can play in both (`teamOptionsForDivision`). Picking a team pre-ticks its players; a stand-in can be unticked and a player added by OpenDota id. Without a champion the dialog warns "No champions recorded; add them in Player management". The typed `END SEASON` confirmation follows.
- **Saving:** `POST /admin/season/end` takes an optional `champions: [{division, team_name, player_account_ids}]` (at most one team per division; ids 1 to 2^63−1). In the same transaction as the archive, it inserts the awards, the champions and one `played` row per player with a scored match, all with source `season_end`. Rows already entered by hand are kept (`INSERT … ON CONFLICT DO NOTHING`). Each fantasy winner gets the `season_winner` user tag.
- **Atomic:** if recording fails, nothing is committed and the call answers 500 with a generic "Recording accolades failed; nothing was archived" (the log keeps the traceback).
- **Response:** adds `accolades`, `awards`, `champions` and `played`; `note` when the season had no scored matches, `warning` when no champions were given.
- **Audit:** `admin_season_archived` adds `accolades=N champions=M` (N counts every row recorded).

## Admin management (Player management)

- **Buttons:** **Mark champions** and **Add accolade** sit next to **Add**. The "Champions and accolades" table under the pool lists every row (Season, Title chip, Winner, Value, Source, Edit, Remove). Champion rows of one season and division collapse into one "[Team] · N players" row: **Edit** opens Mark champions filled in, **Remove** clears the set after a confirmation. The pool rows show each player's titles as chips (pips at phone width).
- **Mark champions:** two ways to start, one editable roster:
  - **From this season:** the live season, a division and a team from the preview (the division's teams listed first); its players fill the roster.
  - **Past season:** "Season 1" to the last ended season (plus any season already in the record), a typed team name and players by OpenDota id. Nothing depends on current teams or players.
  - **Roster editor:** one row per player (OpenDota id, name, Remove), and **+ Add player** (the paste box for "`<id> <name>`" lines was removed in #214; the name field takes the remaining width of the row). Typing an id fills an empty name from the pool, else from earlier accolade rows. A note shows "6 players (usually 5)" when the count isn't 5. Each id must be a positive whole number and appear once; each row needs a name (`validateChampionRoster`, checked again by the server).
  - **Saving** calls `PUT /admin/season-champions`, which makes that season and division's champions exactly the list shown.
- **Add accolade:** season, kind (Most Points, Best Average, Best Single Match, Fantasy Winner, Played), a player (OpenDota id and name, filled from the pool) or a username for Fantasy Winner, and an optional value. Played takes several "`<id> <name>`" lines at once.

## Backfill of Played

`backend/scripts/backfill_played.py` is an operator tool, like `backfill_bench.py`. Each division is its own OpenDota league. Past seasons' leagues (S4–S16) are listed in `backend/scripts/kanaliiga_leagues.json`, and `--all` backfills every season in it except the live one, with a call budget (`--max-calls`, default 900) and a full report. That run, the league table and the run book are in [season-participation-backfill.md](season-participation-backfill.md) (#212).

```
cd backend
python scripts/backfill_played.py --all --dry-run
python scripts/backfill_played.py --all
# one season: from the league file, else found by name ("Kanaliiga Season 14", "Kanaliiga Season 14 Lower")
python scripts/backfill_played.py --season "Season 14" --dry-run
python scripts/backfill_played.py --season "Season 14"
# or name the leagues; the label comes from their names
python scripts/backfill_played.py --league <div1 id> --league <div2 id> --dry-run
```

- **Season label:** each `--league`'s OpenDota name is read (`ingest.get_league_info`, cached) and "Season N" parsed from it. `--season` is optional: given with leagues, it must agree with their names (otherwise an error, nothing written); it is required only when the names carry no number (then that label is used). Leagues that name different seasons are an error.
- **League file first:** `--season "Season N"` without `--league` takes the season's leagues from the league file when it lists the season (Season 4's league is named just "Kanaliiga"). Explicit `--league` ids take precedence.
- **Discovery:** for a season not in the file, `--season "Season N"` without `--league` reads OpenDota's league list (`/leagues`) and takes the leagues named "`<prefix>` Season N", with or without a division suffix ("Lower", "Lower Division"); `--name-prefix` defaults to "Kanaliiga". It prints each league found. **Seasons 1–4 have no numbered OpenDota league** (Season 4's unnumbered one is in the league file): the script says so and points to the Add accolade Played paste.
- **Rows:** every `account_id` in the leagues' matches gets one `played` row for the season, with source `admin`.
- **Names:** the current pool name, else the match's `personaname` (capped at 100 characters), else "Player <id>". Anonymous slots, and any account id that isn't a whole number in 1..2^63−1 (booleans included), are skipped and counted. Invalid match ids are skipped.
- **Safe to rerun:** `INSERT … ON CONFLICT DO NOTHING`. League names and fetched matches are cached in a local JSON file (`--cache`, default `backfill_played_cache.json` in the working directory, git-ignored), so an interrupted run resumes without fetching them again. It waits `--pause` seconds (default 1.2) before each OpenDota call after the first.
- **Report:** per season, "matches, players, new rows, anonymous slots skipped, already recorded, unreadable matches"; `--all` adds totals and the seasons-per-player distribution. `--dry-run` prints it (and what discovery found) and writes nothing. An unreadable match isn't cached, so the next run retries it.
- **Budget:** `--max-calls` caps OpenDota calls per run (default 900; cache hits don't count). A budget stop exits 2 with "Budget used: resume to continue from Season N"; finished seasons are recorded.
- **Audit:** one `admin_accolade_added` entry per season, detail `season_label=… played=N source=backfill`, actor "script".
- **Errors:** an invalid league file or a season that can't be resolved writes nothing; a league OpenDota can't return (an error, an empty answer or anything but a list of match ids) is reported and nothing is recorded for it. The exit code is 1 in both cases.
- **Operator input:** the script stores no league ids; they live in the league file. Take a backup first (`bash scripts/backup-db.sh`). Seasons with no reachable league use the Add accolade Played paste.

## Cards

- **Symbols:** every card shows the player's accolade pips as an HTML overlay (`.card-pips`) stacked down the card's right edge, below the top corner and beside the art, sized in em from the card's width. It is not part of the card image, so pips stay hoverable and a later accolade shows without rebuilding images. User tags show as their own pips down the card's left edge (`.card-tag-pips`, issue #217; see [Tag Symbols on Cards](tag-symbols-on-cards.md)). The card viewer lists the player's titles as chips below the card. Views: card viewer and draw reveal (`_renderCardAccolades` in `app-cards.js`), My Team roster and bench (`_cardSlotHTML` in `app-roster.js`).
- **Data:** the frontend loads `GET /accolades` once per page (`loadAccolades` in `app-globals.js`) and redraws the roster's pips when it arrives.
- **Holo roll:** when `draw_card` or `draw_booster` creates a Legendary for a player with a `champion` accolade in a season other than the live one, it becomes Holo with probability `holo_chance` % (`accolades.roll_holo`), stored as `cards.is_holo = true`. A player removed from the champion record loses eligibility for later draws; cards already drawn as Holo stay Holo.
- **A Legendary in every rule:** `card_type` stays `legendary`; points, modifiers, roster rules, `GET /deck` and boosters are unchanged. Draw, roster, collection (`collection_for_user`) and card detail responses add `is_holo`; card detail also returns `player_id`, which the viewer uses for the pips and the player link.
- **Only champions:** award winners who aren't champions get pips but never Holo; `holo_chance = 0` disables Holo.
- **In the UI:** the rarity label reads "Legendary · Holo". The draw reveal plays one iridescent sweep over the card art (`.reveal-img-wrap--holo`), off under reduced motion.
- **Holo art:** see [Card Image Generation](card-image-generation.md). `Card_Template_Holo.png` when present, else the Legendary template with a generated sheen.

## Accolade symbols

Each kind has a Lucide icon, a colour token (`--accolade-*`, in both copies of `colors_and_type.css`) and a plate: filled for champions, outlined for awards, muted for Played. The symbol table is in the design system README (`.claude/skills/README.md`, "Accolade symbols").

| Kind | Name | Icon |
|---|---|---|
| `champion` (div1) | Div 1 Champion | `crown` |
| `champion` (div2) | Div 2 Champion | `trophy` |
| `most_points` | Most Points | `flame` |
| `best_average` | Best Average | `gauge` |
| `best_match` | Best Single Match | `zap` |
| `fantasy_winner` | Fantasy Winner | `medal` |
| `played` | Played | `calendar-check` |

- **Compact (pips):** one pip per earned kind in this order, with a count from two. Played comes last, muted, and always shows its seasons count. The tooltip reads "Div 1 Champion · S16 with Reds, S15 with Blues" (newest first; champions name the team); Played compresses runs ("Played · 12 seasons: S1–S10, S14, S16"). Each pip is focusable and carries the same text as `aria-label` ("Div 1 Champion, 2 times: …"). The tooltip opens on hover, focus or tap and closes on Escape, blur, mouse leave or a tap elsewhere. Used on cards, in the Players list Titles column and in the popup header.
- **Expanded (chips):** one chip per accolade, such as "S16 Div 1 Champion", newest season first, champions first within a season. Used in Player management, the popup timeline and History. At phone width, Player management shows pips instead (`.accolade-swap`).
- **Fantasy Winner on a player:** shown only while the winning user has a Steam-verified link (`users.steam_id` and `users.player_id` on a full, non-demo account), resolved when read (`accolades._linked_users` through `player_links.verified_links`, the same rule as `own_card.is_candidate`; #209). Linking your account to your player with Steam makes your fantasy win visible on your player's cards and in public lists, which shows that your username belongs to that player; unlinking removes it. A typed (self-reported) player id is never trusted for this, so nobody can put a Fantasy Winner pip on another player.
- **Code:** `ACCOLADE_KINDS` in `backend/accolades.py` and `frontend/app-globals.js` (a test keeps them in sync). Every view renders through `accoladePipsHtml(accolades, {omitPlayed})` and `accoladeChipsHtml(accolades)`; the pip and chip CSS is in the SHARED STATES section of `style.css`. All names are escaped with `_escHtml`.

## Where it shows

- **Players tab:** a Seasons column (the count in tabular numbers, one bar per season for the last six known seasons: grey played, amber champion season, empty not played; hovering the count lists the seasons) and a Titles column of pips, both sortable. Filter chips All, Champions and New this season (one season played, the live one). There is no Veteran status.
- **Player popup:** pips under the name, and an Accolades section (`renderPlayerAccolades`, self-contained for the planned popup redesign): a "Holo unlocked" banner for past champions, counts (champion titles, season awards, seasons played) and a timeline by season with chips, including "S16 Played · 7 matches" for the live season.
- **History tab:** a top-level tab after Leaderboards (`app-history.js`). One panel per season, newest first: the Div 1 and Div 2 champion teams headed by their chip, each player with a Holo badge ("Holo from next season" for the current season's champions, who are not Holo-eligible until the season ends), the four awards as chips with names and values, and the Played count. A Hall of fame sidebar ranks players by titles (champion plus awards, not Played) with their pips. Empty state: "No season history yet."

## Endpoints

| Method and path | Access | Notes |
|---|---|---|
| `GET /history/seasons` | public | `{current_season, seasons: [{season_label, season_short, champions: {div1, div2}, awards: {most_points, best_average, best_match, fantasy_winner}, played_count}], hall_of_fame: [{player_account_id, player_name, titles, champion_titles, award_titles, accolades}]}`; no user ids (fantasy winners by username) |
| `GET /accolades` | public | `{current_season, current_season_short, players: {"<player id>": [{kind, division, season, season_short, team_name, value, match_id}]}}`; Played includes the live season; fantasy winner only through a current Steam-verified link; no user ids or usernames |
| `GET /players`, `GET /players/{id}` | public | add `seasons_played`, `seasons` (newest first) and `titles` (champion and award accolades, newest first); list rows also carry `seasons_counted_from` (the first season counts start from, 4, #212); the detail also adds `accolades`, `current_season`, `current_season_matches` and `holo_unlocked` |
| `GET /admin/season/accolades-preview` | admin | see End Season |
| `POST /admin/season/end` | admin, re-auth, typed confirmation | optional `champions` |
| `PUT /admin/season-champions` | admin, re-auth | `{season_label, division, team_name, players: [{account_id, name}]}` (at most 50); replaces the set in one transaction; an empty list clears the division; 422 on duplicate, non-positive or oversized ids, empty names, an unknown division, or players without a team name; audit `admin_champions_set` with season, division and `added=` / `removed=` |
| `GET /admin/season-accolades?season=&kind=` | admin | every row, newest season first |
| `POST /admin/season-accolades` | admin, re-auth | one row (409 on a duplicate) or a list of up to 500 (rows already recorded are skipped and counted: `{added, skipped}`); validates kind, division and player or user (a fantasy winner must be an existing website account that is not a tester, by id or username; a Twitch viewer soft account or a tester answers 422); audit `admin_accolade_added` |
| `PATCH /admin/season-accolades/{id}` | admin, re-auth | `value`, `player_name`, `team_name`, `username`; 404 when missing; audit `admin_accolade_updated` |
| `DELETE /admin/season-accolades/{id}` | admin, re-auth | audit `admin_accolade_removed`; a `season_winner` tag already granted stays |

The admin routes live in `backend/routers/admin_accolades.py` and `backend/routers/admin_season.py`, the public ones in `backend/routers/history.py`. Admin write routes stay on the global rate-limit baseline, like every admin route ([Action Throttling](action-throttling.md)).

## Schema

| Table | Column | Notes |
|---|---|---|
| `season_accolades` | (new table) | Created by `create_all`; kept by Season Reset |
| `cards` | `is_holo` | BOOLEAN NOT NULL DEFAULT 0, migration `040_cards_is_holo` |

Deploys with migration 040: run `bash scripts/backup-db.sh` first.

## Configuration

| Weight | Default | Description |
|---|---|---|
| `holo_chance` | `20` | Percent chance that a past champion's Legendary is drawn as Holo (seeded by `seed.py`, shown in Scoring config, overridable with `WEIGHTS_JSON`) |

No new environment variable.

## After deploy (by hand)

With Add accolade and Mark champions, enter the S15 awards (Glete: most points; Keikari [PV]: best average; ImperialZod: best single match; Jiri: fantasy winner) and the S15 champion teams (Mark champions › Past season). Then run the Played backfill for S4–S15 with `--all` (`--dry-run` first; run book in [season-participation-backfill.md](season-participation-backfill.md)); S1–S3 have no OpenDota league and use the Played paste.

