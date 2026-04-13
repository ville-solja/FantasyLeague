## Terminology

**League** — A tournament in OpenDota. The ID that ties together all players, teams, and matches. Multiple leagues (divisions) can be ingested simultaneously — cards are generated per-league.

**Series** — A best-of-N between two teams on a given fixture date. One row in the schedule sheet; one or more individual matches in the database.

**Match** — A single played map. Contains two teams, 10 players, and per-player performance stats from the OpenDota API.

**Player** — A participant tied to the current league. Names and avatar images are resolved from OpenDota player profiles after ingestion.

**Team** — A team taking part in the league. Names are extracted from match data.

**Card** — A player instance that can be owned by a user. Cards are generated dynamically per league on ingestion: 1 legendary, 2 epic, 4 rare, 8 common per player.

**Deck** — The pool of unowned cards available to draw from.

**Roster** — The active cards a user has selected (max 5). The editable roster is snapshotted each Sunday midnight into a weekly locked roster. Weekly value is the sum of fantasy points earned by those locked cards during that week's matches only.

**Bench** — List of cards that the user owns, but are not in the selected weeks roster

**Weight** — A multiplier applied to a stat when calculating fantasy points. Stored in the database and adjustable via the admin panel.

**Fantasy Points** — Points earned by a player in a single match, calculated as the weighted sum of their performance stats.

**Modifier** — Enchancements on a card that modifies the basis for counting the fantasy points.

**Tab** — Technically the "pages" or "views" on the frontend are just tabs, but the terms can be used quite interchangeably.

**Token** — Currency that governs how many times a user can perform certain actions. They are then obtainable in various ways that involve engaging with the league.

**Rarity** — Value that is determining how commonplace the given card is. See cards.md for detailed and up to date information on card creation, modifiers and rarities.

**Weekly Roster Entry** — An immutable snapshot of a user's active cards for a specific week, created at lock time. Used for scoring and for historical week review.

**Season Points** — The cumulative fantasy points a user has earned across all locked weekly roster entries during the season. Visible in the season leaderboard and on the My Team tab.

**Promo Code** — An admin-created alphanumeric code that grants a configurable number of tokens to each user who redeems it. Each code can be used once per user.

**Admin** — A user with elevated privileges. Can ingest leagues, manage scoring weights, grant tokens, create/delete promo codes, and refresh the schedule cache. Identified by the `is_admin` flag on the user record.

**Week** — A 7-day scoring window anchored to Sundays. Rosters are locked at the start of each week and the snapshot is used to calculate that week's points. See `weeks.md`.

**Week Lock** — The moment a week's match window opens (Monday 00:00 UTC). At lock time: the active roster is snapshotted, the week is marked locked, and every user receives +1 token.

**Week Override** — An admin-assigned mapping that moves a specific match into a different fantasy week than the one its timestamp falls in. Used when matches are played outside their scheduled window.

**Toornament** — The tournament bracket platform (toornament.com) where the Kanaliiga tournament is managed. The app automatically pushes series results there after each ingest cycle. See `toornament.md`.

**Audit Log** — A time-ordered record of significant system events (ingests, token grants, week locks, admin actions). Visible to admins at `GET /audit-logs`.

**Promo Code** — An admin-created alphanumeric code that grants a configurable number of tokens when redeemed. Each code can be redeemed once per user.