# Cards

Cards are the core collectible unit of the fantasy league. Each card represents a real Dota 2 league player and is generated on demand at draw time.

## Card Rarities

Each draw creates one card with a rarity rolled from configurable percentage weights. In API responses the rarity is returned as the `card_type` field with values `"common"`, `"rare"`, `"epic"`, or `"legendary"`.

| Rarity | Default draw rate | Default rarity bonus | Default modifiers granted |
|--------|------------------|---------------------|--------------------------|
| Common | 60% | +0% | 0 |
| Rare | 25% | +1% | 1 |
| Epic | 10% | +2% | 2 |
| Legendary | 5% | +3% | 3 |

**Draw rates** are relative weights (`draw_rate_common`, `draw_rate_rare`, `draw_rate_epic`, `draw_rate_legendary`) set through `WEIGHTS_JSON` (shown read-only in the admin panel under Scoring Weights). They do not need to sum to 100 — proportions are used. Defaults approximate 8:4:2:1 ratios from the old pool model.

**Rarity bonus** is a percentage multiplier applied to the card's total fantasy score after all other calculations. It is configurable via the weights `rarity_common`, `rarity_rare`, `rarity_epic`, `rarity_legendary`, which are percents (`rarity_rare = 1.0` means +1%). In code, `card_utils._load_weights` turns each into the fraction `mod_<type>` (weight / 100), and the multiplier is `1 + mod_<type>`.

### Holo Legendaries

A past season champion's Legendary can be drawn as **Holo** (issue #53). When a draw or a team draw creates a Legendary for a player with a champion accolade in a season other than the current one, it becomes Holo with probability `holo_chance` % (a weight, default 20; `0` turns Holo off), stored as `cards.is_holo`. A Holo card is a Legendary in every rule: `card_type` stays `"legendary"`, and points, modifiers, roster rules, `GET /deck` and team draws are unchanged. Only the art differs, and card responses add `is_holo`. Award winners who aren't champions never get Holo. Cards also show the player's accolade pips as an HTML overlay. See [Season Champions, Accolades and Holo Cards](../reference/season-winners-and-holo-cards.md).

## Drawing Cards

- Costs **1 token** per draw.
- Rarity is rolled from the configured draw-rate weights at draw time.
- A player is chosen with a proportionality bias: players the user does not yet own any card of (at any rarity) are preferred. Among those, players with fewer total cards in the user's collection are weighted higher.
- If the user already owns at least one card of every active player, the uniqueness constraint is relaxed and any player may be selected.
- If no players exist in the database at all, the draw returns 409.
- Each draw **creates a new Card row** — there is no shared pre-generated pool to exhaust.
- The new card joins the **active roster** when fewer than `ROSTER_LIMIT` (default 5) cards are active and no active card has the same player; otherwise it goes to the **bench**. The check and the activation are one conditional `UPDATE` (`_activate_card_atomic`), so fast or concurrent draws can't overfill the roster (#185; see [Atomic Roster and Token Operations](../reference/atomic-roster-and-token-operations.md)).

## Own Player Card

A league player who links Steam (or signs up through Steam) gets one free **common** card of themselves when their verified player id is an active player in this season's pool (issue #188). It is created like a draw card (modifiers, stored points, roster or bench by the same rule as above) but costs no token. It is given once per account and once per league player (`own_player_card_grants`), and not at all when the account already owns a card of that player. Draws then treat the granted card as owned like any other card (they prefer unowned players until the user owns every active player, or every player of the team for a team draw). A popup on the next page load shows the card in the card viewer and explains why. A season reset clears the grants with the cards. Details: [Steam Login › Own player card](../reference/steam-login.md#own-player-card-issue-188).

## Deck Structure

Cards are generated dynamically at draw time rather than from a pre-seeded shared pool. `GET /deck` returns the number of distinct `(player, rarity)` combinations the requesting user has not yet drawn. This count decreases by one each time the user draws a new unique combination.

Each Card row carries `generation=1` by default. The `league_id` field is nullable for dynamically created cards. Existing pre-seeded cards (from before the migration) are unaffected.

## Card States

| State | Meaning |
|-------|---------|
| Benched | Owned by a user, not in any active roster slot |
| Active | In the user's active 5-card roster for the upcoming week |
| Locked | Active roster was snapshot at week lock — card scores for that week |

## Scoring

Fantasy points for a card are derived from the real-life player's match stats during the locked week:

```
points = kills                   × kill_weight
       + assists                 × assists_weight
       + last_hits               × last_hits_weight
       + denies                  × denies_weight
       + gold_per_min            × gpm_weight
       + obs_placed              × obs_weight
       + towers_killed           × tower_weight
       + roshan_kills            × roshan_weight
       + teamfight_participation × participation_weight
       + camps_stacked           × stack_weight
       + rune_pickups            × rune_weight
       + firstblood_claimed      × firstblood_weight
       + stuns                   × stun_weight
       + max(0, death_pool − deaths × death_deduction)
```

The death contribution awards `death_pool` points (default 3.0) for surviving with 0 deaths, deducting `death_deduction` (default 0.3) per death, floored at 0. A player with 10 or more deaths scores 0 from this component.

Card points are defined **per match**: the death term is floored at 0 in each match separately, so one bad game cannot eat another game's survival points. This matches the Players tab's per-match `fantasy_points`. A card's week total is the sum of its per-match points for the scored matches in the week, and its season total is the sum of its week totals over the locked weeks in which it counted (after bench substitution: an active entry not subbed out, or a subbed-in bench entry).

Each card's per-match points are stored in `card_match_points` when their inputs change, and My Team, the weekly and season leaderboards and End Season all sum the stored values. See [Stored Card Points](../reference/stored-card-points.md).

Weights come from `backend/seed.py` defaults plus any `WEIGHTS_JSON` overrides, applied by `seed_weights()` at startup. The admin panel's **Scoring Weights** table is read-only. When the weights differ from the ones the stored card points were built with, the startup check rebuilds the stored points automatically; `POST /recalculate` (Admin → Recalculate) also rebuilds them.

## Card Modifiers

Card modifiers are per-stat bonuses assigned to a card at draw time. They boost the contribution of a specific stat to that card's fantasy score.

### How modifiers work

Each modifier targets one of the scoring stats and carries a `bonus_pct` percentage value.

Valid modifier targets: `kills`, `assists`, `deaths`, `gold_per_min`, `obs_placed`, `last_hits`, `denies`, `towers_killed`, `roshan_kills`, `teamfight_participation`, `camps_stacked`, `rune_pickups`, `firstblood_claimed`, `stuns`

The modifier always benefits the card owner:
- For **standard stats** (all except deaths):  
  `contribution = stat_value × weight × (1 + bonus_pct / 100)`
- For **deaths**:  
  `contribution = max(0, death_pool − deaths × death_deduction) × (1 + bonus_pct / 100)`, per match — the survival bonus is amplified. This modifier is most valuable on players who rarely die; it has no effect when the death contribution is already 0.

### Full scoring formula with modifiers

```
For each standard stat (kills, assists, last_hits, denies, gpm, obs, towers, roshan,
                        participation, stacks, runes, firstblood, stuns):
  base = stat_value × stat_weight
  points += base × (1 + modifier_bonus_pct / 100)   if modifier present
  points += base                                      if no modifier

For deaths (one match):
  base = max(0, death_pool − deaths × death_deduction)
  points += base × (1 + modifier_bonus_pct / 100)   if modifier present
  points += base                                      if no modifier

If the player was that match's MVP, add the MVP bonus
(the match's own fantasy_score × mvp_bonus_pct / 100).

After summing all contributions:
  match_points = stat_total × (1 + rarity_bonus_pct / 100)
  (rarity_bonus_pct is the rarity_<type> weight; 1 + mod_<type> in code)

A card's week or season points are the sum of its stored match_points
(the card_match_points.points column) over the scored matches in scope.
```

### Modifier assignment at draw time

When a card is drawn from the deck, modifiers are randomly assigned:

1. **How many**: determined by `modifier_count_<rarity>` weight (e.g. `modifier_count_rare = 1` → 1 modifier on a rare card).
2. **Which stats**: randomly sampled without replacement from the 14 valid stat keys (the 13 scoring stats in `SCORING_STATS` + `deaths`).
3. **Bonus %**: all modifiers on a card share the same `modifier_bonus_pct` value.

All three settings are weights set through `WEIGHTS_JSON` (shown read-only in the admin panel under Scoring Weights).

### Modifier visibility

Modifiers are rendered directly onto the card's PNG image (see `reference/card-image-generation.md`) — that is the only place they're shown. There is deliberately no separate text/pill rendering anywhere in the UI (My Team roster rows, the reveal modal, or the card detail popup); the values are already readable on the card image itself, so a second text rendering would be duplicate information.

### Modifier configuration (admin)

| Weight key | Description | Default |
|---|---|---|
| `modifier_count_common` | Number of modifiers on a Common card | 0 |
| `modifier_count_rare` | Number of modifiers on a Rare card | 1 |
| `modifier_count_epic` | Number of modifiers on an Epic card | 2 |
| `modifier_count_legendary` | Number of modifiers on a Legendary card | 3 |
| `modifier_bonus_pct` | % bonus each modifier grants | 10 |

Modifier counts apply to **newly drawn cards only** — existing cards in users' rosters are not retroactively updated when the count weights change.

### Modifier Reroll

A user can spend **1 token** to discard a card's current modifiers and generate a new random set in their place. The card's rarity, player, and league are unchanged — only the `card_modifiers` rows are replaced.

#### `POST /roster/{card_id}/reroll`

Requires authentication. The card must be owned by the calling user.

**Cost:** 1 token, deducted on success.

**Behaviour:**
1. All existing `CardModifier` rows for the card are deleted.
2. New modifiers are assigned using the same random logic as draw time: count determined by `modifier_count_<rarity>`, stats randomly sampled without replacement, bonus set by `modifier_bonus_pct`.
3. The action is recorded in the audit log (`reroll_modifiers`).

**Response:**
```json
{
  "modifiers": [{"stat": "kills", "bonus_pct": 10.0}],
  "tokens": 4
}
```

Returns the new modifier list and the user's remaining token balance. Returns 409 if the user has no tokens. Returns 400 `"Common cards cannot be rerolled"` if the card's rarity is `common` (no modifier stats to reroll) — no token is deducted in that case. The Reroll button is also hidden client-side for common cards. See `reference/prevent-common-card-reroll.md`.

The reroll applies the **current** `modifier_count_<rarity>` and `modifier_bonus_pct` weight values, so a reroll may produce a different number of modifiers than the card originally had if an admin has changed the weights since the card was drawn.

### Extending the modifier system

The current system uses a single uniform `bonus_pct` for all modifiers. Future extensions could include:
- Per-stat modifier pools with different bonus ranges (e.g. kill modifiers stronger than GPM modifiers)
- Negative modifiers (penalties) drawn alongside bonuses
- Rarity-specific bonus ranges (e.g. Legendary cards get higher `bonus_pct` than Rare)
- Special named modifiers with flavour text
- Card-specific modifiers that affect only one player's known strengths

To add a new modifier type, add a new row to the `card_modifiers` table with the appropriate `stat_key` and `bonus_pct`. Any `stat_key` present in `SCORING_STATS` (defined in `backend/scoring.py`) will be applied automatically.

---

## Roster Endpoints

### `GET /roster/{user_id}`

Returns the calling user's cards split into `active` and `bench` lists, with per-card fantasy points scoped to the requested week.

**Query parameter:** `week_id` (optional integer). Omit to use the current editable week.

- For a **locked** week: returns the `WeeklyRosterEntry` snapshot for that week with points from matches played during the week's window. `active` holds the counted entries (active not subbed out, plus subbed-in bench cards, each shown in the `slot_index` of the card it replaced). `bench` holds the rest: subbed-out cards first, then the saved bench in its lock-time `bench_order`. A week locked before the bench was saved (issue #129) has an empty `bench`.
- For the **current editable** week: returns all owned cards of active players from the `cards` table, split by `is_active`, with running points accumulated so far.

Every card also carries `rank_tier` and `leaderboard_rank` (the player's last known rank medal, null when unranked; see [Player Rank Medals](../reference/player-rank-medals.md)) and `team_id`, `team_name` and `team_logo_url` (the player's most recent team; `team_logo_url` is null when the stored logo's host isn't in `LOGO_HOST_ALLOWLIST`, #171). Every card carries `subbed_in`, `subbed_out` (booleans) and `subbed_in_for` (the replaced card's player name on a subbed-in card, otherwise null); all are false/null outside a locked week. `substitutions_done` is true once the week's substitutions have run (also inside `week`), and `substitution_delay_hours` is the `SUBSTITUTION_DELAY_HOURS` value. See [Automatic Bench Substitution](../reference/automatic-bench-substitution.md).

```json
{
  "active": [{ "id": 42, "card_type": "rare", "player_name": "SomePlayer", "total_points": 34.5, "modifiers": [...],
               "subbed_in": false, "subbed_out": false, "subbed_in_for": null, ... }],
  "bench":  [...],
  "combined_value": 130.2,
  "season_points": 420.0,
  "tokens": 4,
  "week": { "id": 7, "label": "Week 7", "is_locked": true, "start_time": 1760000000, "end_time": 1760600000,
            "substitutions_done": false },
  "substitutions_done": false,
  "substitution_delay_hours": 24.0
}
```

`week` is null when there is no requested or upcoming week. `version` (#186) is the version of the stored, editable layout (whatever `week_id` asks for), which `PUT /roster` checks: the first 16 hex characters of SHA-256 over `active:<ids>|bench:<ids>`, with the roster ids in slot order (`-` for an empty slot between cards) and the bench ids in order.

Requires authentication. Returns 403 `"Cannot view another user's roster"` if `user_id` doesn't
match the caller's own ID, unless the caller is an admin (admins can view any user's roster).

---

### `PUT /roster`

Stores the caller's whole roster layout in one transaction (#186); My Team saves with it automatically. Body:

```json
{ "active": [42, null, 17], "bench": [8, 3], "base_version": "4cae17486dcce52c" }
```

`active` has one entry per roster slot (at most `ROSTER_LIMIT`; `null` is an empty slot), `bench` the bench card ids in order (at most 5000, `ROSTER_BENCH_MAX`); card ids are 1 to 2^63−1 (422 otherwise, also in `/roster/swap` and `/roster/reorder`), `base_version` the `version` the layout is based on (1-64 characters). Every card not listed as active is benched first, then the roster cards get their slots and the bench cards their order. Nothing changes when a check fails:

- 409 with header `X-Roster-Conflict: version` when `base_version` no longer matches (the roster changed elsewhere).
- 409 `"A card is listed more than once"`, `"Roster full ({ROSTER_LIMIT} cards max)"`, `"A card for this player is already active"` or `"A removed player can't be on the roster"`; a write the unique index refuses also answers the duplicate-player 409.
- 404 `"Card not found"` for a card the caller doesn't own, as the single-card routes answer.
- 422 for a malformed body; 401 without a session; 429 over `RATE_LIMIT_ROSTER_MUTATION`.

A layout identical to the stored one writes nothing. The answer is the `GET /roster/{user_id}` response for the next editable week, with the new `version`; after a week's lock a save counts from the next week, and `week` names it. Details: [My Team Fluid Roster](../reference/my-team-save-roster.md).

---

### `POST /roster/{card_id}/activate`

My Team uses `PUT /roster` (#186); the single-card HTTP routes below stay for older clients. The Twitch panel has its own `/twitch/roster/...` routes, which reuse these routes' functions (`activate_card`, `deactivate_card`, `swap_roster`).

Moves a benched card into the active roster. Requires authentication; the card must be owned by the caller.

- Returns 409 `"Roster full ({ROSTER_LIMIT} cards max)"` if the user already has `ROSTER_LIMIT` active cards (default: 5).
- Returns 409 `"A card for this player is already active"` if another card for the same player is already active. The partial unique index `ux_cards_owner_player_active` (#185) refuses a second active card for one player at the database level; a write it refuses answers the same 409.
- Returns `{ "status": "ok", "card_id": N }` on success.

---

### `POST /roster/{card_id}/deactivate`

Moves an active card to the bench. Requires authentication; the card must be owned by the caller.

Returns `{ "status": "ok", "card_id": N }`.

---

### `POST /roster/reorder`

Sets `slot_index` (drag-and-drop display position) for a list of the caller's own cards within
their current zone (active or bench). Accepts `{"card_ids": [...]}` for sequential positions
(index in the array = new `slot_index`), or `{"card_ids": [...], "slot_indexes": [...]}` to
assign explicit positions instead. Requires authentication. See
`reference/my-team-drag-and-drop.md`.

---

### `POST /roster/swap`

Atomically activates a bench card into a given slot while deactivating an active card, applying
the same duplicate-player guard as `activate`. Requires authentication. Returns 404 if either
card isn't found in the expected zone; 409 on a duplicate-player conflict. The outgoing card is
benched first, in a statement that checks it is still active; when it isn't (another swap took
it), nothing changes and the answer is 404, as when the card isn't in the expected zone (#185). See `reference/my-team-drag-and-drop.md`.

---

## Card Endpoints

### `GET /deck`

Returns the number of distinct `(player, rarity)` combinations the requesting user has not yet drawn, grouped by rarity.

- **Authenticated:** returns the per-rarity count of combinations the user can still draw uniquely.
- **Unauthenticated:** returns the total combinations across all players (4 rarities × number of players).

```json
{ "common": 12, "rare": 12, "epic": 12, "legendary": 12 }
```

The frontend displays this as "X draws available". The count decreases by 1 each time the user draws a new unique `(player, rarity)` combination. No authentication required.

---

### `GET /cards/{card_id}`

Returns full detail for a single card owned by the authenticated user. Returns 404 if the card does not exist or is not owned by the caller.

```json
{
  "id": 42,
  "card_type": "rare",
  "player_name": "SomePlayer",
  "avatar_url": "https://...",
  "rank_tier": 54,
  "leaderboard_rank": null,
  "team_name": "SomeTeam",
  "team_logo_url": "https://...",
  "modifiers": [{ "stat": "kills", "bonus_pct": 10.0 }]
}
```

`team_name` and `team_logo_url` are resolved from the player's most recent ingested match. `team_logo_url` is null when the stored logo's host isn't in `LOGO_HOST_ALLOWLIST` (#171; see [Twitch Panel Abuse Limits](../reference/twitch-panel-abuse-limits.md)).

---

### `POST /draw`

Draws one card. A new Card row is created on demand — no pre-generated pool is required. Requires authentication.

**Cost:** 1 token, deducted on success. Returns 409 if the user has no tokens, and 409 if no Player records exist.

**Response:**
```json
{
  "id": 42,
  "card_type": "rare",
  "player_id": 123456789,
  "player_name": "SomePlayer",
  "avatar_url": "https://...",
  "rank_tier": 54,
  "leaderboard_rank": null,
  "team_name": "SomeTeam",
  "team_logo_url": "https://...",
  "is_active": true,
  "modifiers": [{ "stat": "kills", "bonus_pct": 10.0 }],
  "tokens": 4
}
```

`is_active` is `true` if the card was placed directly into the active roster, `false` if it went to the bench. `rank_tier` and `leaderboard_rank` are the player's last known rank medal (null when unranked; see [Player Rank Medals](../reference/player-rank-medals.md)); `GET /cards/{card_id}` carries them too. `team_logo_url` is null when the stored logo's host isn't in `LOGO_HOST_ALLOWLIST` (#171).

The card is placed in the active roster when fewer than `ROSTER_LIMIT` cards are active and no active card has the same player; otherwise it goes to the bench, and the draw still succeeds. `is_active` is what was stored. The action is recorded in the audit log (`token_draw`).

---

### `GET /cards/{card_id}/image`

Generates and returns a PNG card image for any card (owner not required). Returns `Content-Type: image/png` with `no-cache` headers.

Returns 404 if the card does not exist. Returns 503 if the Pillow image library is not available in the runtime environment. Returns 429 after 60 requests a minute from one IP (`RATE_LIMIT_CARD_IMAGE`).

The image includes the player avatar, team logo, card rarity border, player name, and any stat modifier labels. Used by the frontend draw reveal modal.

---

### `GET /deck/booster` and `POST /draw/booster/{team_id}`

A variant of the standard deck/draw pair, restricted to one team's player roster at a
configurable Token cost (`team_booster_cost`, default 3) instead of the usual 1. Duplicate
prevention and response shape otherwise match `GET /deck` and `POST /draw`. See
`reference/team-booster-draws.md` for the full endpoint contract and configuration.
