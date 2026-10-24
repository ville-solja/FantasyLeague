# Player Rank Medals

Shows each player's last known Dota 2 rank medal (Herald to Immortal, with stars, and the Immortal leaderboard place) in the player popup, the card viewer and on the card PNG (issue #221). Plan: `markdown/plans/plan-issue-221-player-rank-medals.md`.

---

## Data

OpenDota's `GET /players/{account_id}` returns top-level `rank_tier` (tens digit: medal 1 Herald … 8 Immortal; ones digit: stars 1–5, 0 for Immortal) and `leaderboard_rank`. They are stored on `players` as `rank_tier`, `leaderboard_rank` and `rank_fetched_at` (all nullable INTEGER; migration `040_players_rank`).

`backend/player_rank.py` is the one place for the rules:
- `parse_rank(data)` returns `(rank_tier, leaderboard_rank)`. A tier that is not an integer from 10 to 80 with a known medal is `None`. The leaderboard place is kept only for a positive integer on tier 80.
- `medal_name(tier, lb)` returns "Legend 4", "Immortal", "Immortal #123", or `None`. A valid tier whose ones digit is not 1–5 (for example 10 or 17) gives the bare medal name; `rankMedalHtml` does the same and draws no stars.
- `apply_rank(player, data, now)` stores both values and sets `rank_fetched_at`.

Notes:
- **Approximate:** the rank is the last one OpenDota saw, not a live value.
- **Often missing:** it's null for uncalibrated players or players with private match data, and then no medal shows.
- **No MMR:** the app shows the medal and stars only, never an MMR number.

## Refresh

- Adding a player (`POST /admin/players`, `POST /admin/players/bulk`) and the name/avatar enrichment (`enrich_players`) store the rank from the response they already fetch.
- The background profile enrichment (`run_profile_enrichment`) starts with a rank phase, before the facts phase. It refreshes active pool players whose `rank_fetched_at` is null or older than `PROFILE_ENRICHMENT_COOLDOWN_HOURS`, oldest first, up to the batch size. Players with no ingested matches are included. See `player-profile-enrichment.md`.
- A null rank from OpenDota is stored as null. A failed request (no response, or a body without a `profile`) keeps the previous rank and timestamp, so the player is retried next cycle.

## Display

The website draws its own badge, `rankMedalHtml(tier, lb, fetchedAt)` in `frontend/app-globals.js`: a CSS shape per medal in the medal colour, the medal name, and the stars as ★ marks. No images, no Dota CDN, no league name. The badge has `role="img"` with `aria-label="Rank: Legend 4"` and the title "Last known rank from OpenDota, <date>" (no date when unknown). A null tier returns an empty string.

Colours are tokens `--medal-herald` … `--medal-immortal` in `frontend/colors_and_type.css` (and the `design/` copy). Each has at least 6:1 contrast on `--bg-card` and the rarity reveal backgrounds. Rules are under "RANK MEDAL (issue #221)" in `style.css`.

It appears:
- in the player popup header, after the team name;
- under the card image in the card viewer and the draw reveal (`#revealRank`, hidden when empty);
- on the card PNG, in the rank slot under the rarity gems (#218). `image._draw_rank_medal` draws the same medal shape and colour with Pillow, the medal name and the stars, or "#N" for an Immortal with a leaderboard place. The slot is empty when the rank is null. See [Card Image Generation](card-image-generation.md).

## Endpoints

### `GET /players/{player_id}`
Returns `rank_tier`, `leaderboard_rank` and `rank_fetched_at`.

### Card data (`routers/cards.py`)
`rank_tier` and `leaderboard_rank` are in each card of `GET /roster/{user_id}` (My Team, both the open-week and locked-week queries), in the `POST /draw` and `POST /draw/booster/{team_id}` responses, and in `GET /cards/{card_id}`. The Twitch panel's collection does not include them (it shows the card PNG, which draws the medal).

### `POST /admin/enrich-profiles`
Returns `rank_updated`, the number of ranks stored in that run.
