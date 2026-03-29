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