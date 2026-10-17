# Season Champions, Accolades and Holo Cards

Seasons remember who won and who played. Each season has **champions**, the 10 players of the Div 1 and Div 2 winning teams. Champions get Holo cards in later seasons and a Champion accolade. Seasons also hand out **accolades** that add up over time: most points, best average, best single match, fantasy winner and Played (1+ match). Everything sits in a record that Season Reset never touches. It drives card stickers, the Holo roll, veteran counts in the Players list, the player popup and the History tab. Resolves GitHub issues #50, #53 and #105; plan: `markdown/plans/plan-issue-50-season-winners-and-holo-cards.md`; design canvas: https://claude.ai/artifact/CXUJ4FJ617oaqzAdf54iwr.

---

## Record *(planned)*

- **Storage:** the `season_accolades` table: season label, kind (`champion`, `most_points`, `best_average`, `best_match`, `fantasy_winner`, `played`), division and team name for champions, player (OpenDota account id and name) or user (id and username), value, match id, and source (`season_end` or `admin`).
- **Survives Reset:** names are denormalised, so rows outlive Season Reset.
- **Filled by End Season:** it records the awards and one Played row per player with a scored match, plus the champions the admin picks (Div 1 and Div 2 winning teams, with their players pre-ticked).
- **Filled by hand:** admins add or correct entries with **Mark champions** and **Add accolade** in Player management. That covers S15, plus bulk Played by pasting OpenDota ids.

## Cards *(planned)*

- **Stickers:** champion first, then the newest awards; at most three, then "+N". Played is never a card sticker.
- **Holo:** a Legendary of a past champion is drawn as Holo with probability `holo_chance` % (admin weight, default 20), stored as `cards.is_holo`. It is a Legendary in every rule; only the art differs.
- **Holo art:** `Card_Template_Holo.png` (597 × 845) when present, else the Legendary template with a generated sheen.

## Where it shows *(planned)*

- **Players tab:** a seasons-played count with per-season bars (amber for a champion season), a Veteran badge at 3+ seasons, and a Titles column. Filters for Veterans, Champions and New this season.
- **Player popup:** a Holo unlocked banner, counts and a timeline by season.
- **History tab:** per season, the two champion teams and the four awards, plus a Hall of fame.

## Endpoints *(planned)*

- **`GET /history/seasons`:** public; no user ids.
- **`GET /players` (extended):** `seasons_played`, `seasons`, `titles`.
- **`GET /admin/season/accolades-preview`:** admin; awards, Played count, and the season's teams with their players.
- **`POST /admin/season/end` (extended):** optional `champions`.
- **`GET`, `POST`, `PATCH` and `DELETE /admin/season-accolades`:** admin; changes need a recent password check and are audited.

## Schema *(planned)*

| Table | Column | Notes |
|---|---|---|
| `season_accolades` | (new table) | Created by `create_all`; kept by Season Reset |
| `cards` | `is_holo` | BOOLEAN NOT NULL DEFAULT 0, migration 040 |

## Configuration

| Weight | Default | Description |
|---|---|---|
| `holo_chance` | `20` | Percent chance that a past champion's Legendary is drawn as Holo |

---

*This document is a stub created at feature planning time. Fill in implementation details once the feature is built.*
