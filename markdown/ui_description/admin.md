# Admin tab

Visible only to admin users. All actions require an active admin session cookie — client-side `is_admin` alone is not sufficient.

## Ingest League panel

- Input field for an OpenDota league ID.
- **Ingest** button — fetches all matches for that league from OpenDota, calculates fantasy points, seeds player cards into the deck, and enriches player profiles with names and avatars. Safe to re-run; already-stored matches are skipped.

## Refresh Schedule Cache panel

- **Refresh** button — busts the in-memory schedule cache and re-fetches the Google Sheets CSV. Use after the sheet is updated between match weeks.

## Recalculate Fantasy Points panel

- **Recalculate** button — re-applies the current scoring weights to all stored player match stats without re-fetching from OpenDota. Use after adjusting weights.

## Promo Codes panel

- **Create** — enter a code name (auto-uppercased) and a token amount, then click Create. The code can be redeemed by users in the My Team tab.
- **Table** — lists all existing codes with their token amount and redemption count. Each row has a Delete button.

## Token Balances panel

- Lists all registered users with their current token balance.
- Each row has a number input and a **Grant** button to add tokens to that user's balance.

## Scoring Weights panel

- Read-only table of all configured weight keys and values (loaded from `GET /weights`).
- Includes scoring stat weights, death formula params (`death_pool`, `death_deduction`), rarity bonuses (`rarity_common` … `rarity_legendary`), and modifier tuning keys (`modifier_count_*`, `modifier_bonus_pct`).
- Operational changes are made outside the UI (typically `WEIGHTS_JSON` overrides merged on startup and/or direct DB edits to the `weights` table), then use **Recalculate** to backfill `player_match_stats.fantasy_points` if needed.
