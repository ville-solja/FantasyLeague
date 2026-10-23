# Player Rank Medals

Shows each player's last known Dota 2 rank medal (Herald to Immortal, with stars, and the Immortal leaderboard place) in the player popup and the card viewer, and later on the card PNG (issue #221). Plan: `markdown/plans/plan-issue-221-player-rank-medals.md`.

---

## Data

*(planned)* OpenDota's `GET /players/{account_id}` returns `rank_tier` (tens digit: medal 1 Herald … 8 Immortal; ones digit: stars 1–5, 0 for Immortal) and `leaderboard_rank`. They are stored on the player as `rank_tier`, `leaderboard_rank` and `rank_fetched_at`.

- **Approximate:** the rank is the last one OpenDota saw, not a live value.
- **Often missing:** it's null for uncalibrated players or players with private match data, and then no medal shows.
- **No MMR:** the app shows the medal and stars only, never an MMR number.

## Refresh

*(planned)* Adding a player stores the rank from the response it already fetches. The background profile enrichment refreshes ranks older than `PROFILE_ENRICHMENT_COOLDOWN_HOURS` for every pool player, before its facts phase. A failed request keeps the previous rank.

## Display

*(planned)* The website draws its own medal badge (shape and colour per medal, with stars); no images are loaded from a Dota CDN. It appears:
- in the player popup header, with "Last known rank from OpenDota" and the fetch date;
- under the card in the card viewer;
- on the card PNG, in a rank slot of the new templates (#218).

## Endpoints

### `GET /players/{player_id}`
Gains `rank_tier`, `leaderboard_rank` and `rank_fetched_at` *(planned)*.

### Card lists (`routers/cards.py`)
Each card gains `rank_tier` and `leaderboard_rank` *(planned)*.

---

*This document is a stub created at feature planning time. Fill in implementation details once the feature is built.*
