# Plan: Player Rank Medals

## Context
Players in the pool are ordinary Dota 2 players, so their public ranked medal (Herald to Immortal) helps a fantasy player judge them. OpenDota's `GET /players/{account_id}`, which the app already calls for the name and avatar, also returns the player's last known rank. Issue #221 asks whether that rank can be obtained and shown on the player popup and on cards, before the card layout change (#218) so the new templates can reserve a place for it.

**Feasibility.** Yes, with limits:
- **`rank_tier`** is a two-digit number: the tens digit is the medal (1 Herald, 2 Guardian, 3 Crusader, 4 Archon, 5 Legend, 6 Ancient, 7 Divine, 8 Immortal) and the ones digit is the stars (1–5; 0 for Immortal). For example, 54 is Legend 4 and 80 is Immortal.
- **`leaderboard_rank`** is the Immortal leaderboard place, or null.
- **Approximate:** it's an approximation, the last rank OpenDota saw on the player's profile, not a live value.
- **Often missing:** it's null when the player is uncalibrated, has not played ranked recently, or keeps match data private. Some players will have no medal.

I couldn't call OpenDota from the planning environment. The field names come from OpenDota's documented player response and must be checked against a live response in Step 1.

Assumptions:
- **What is shown:** the medal name and stars ("Legend 4"), and "Immortal #123" when there is a leaderboard place. No MMR number: Valve no longer publishes MMR ranges per medal, so an MMR estimate would mislead.
- **Own medal icons:** the app draws its own medal badge (a shape per medal in a medal colour, with stars), as CSS on the website and Pillow on the card. It does not load Valve's rank images from a Dota CDN: no new external host and no image-licensing question.
- **Refresh:** the existing background profile enrichment (`run_profile_enrichment`, 24-hour cooldown) also refreshes the rank, with one extra OpenDota call per player. It does this for every player in the pool, including players with no ingested matches yet. Adding a player (one or in bulk) stores the rank from the response it already fetches.
- **Cards:** the rank goes into the card data the website reads, so the card viewer can show it now. Drawing it on the card PNG is part of #218: each new template gets a rank slot. Today's templates have no free space, and drawing it now would be thrown away with them.
- **Twitch panel:** not part of this issue; the panel shows the card PNG, so it gets the medal with #218.

Resolves GitHub issue #221.

## User Stories

### Store Each Player's Rank Medal
**User story**
As an operator, I want each player's Dota 2 rank medal fetched from OpenDota and kept up to date so that the app can show it without extra calls when someone opens a player.

**Acceptance criteria**
- `players` gains `rank_tier`, `leaderboard_rank` and `rank_fetched_at` (all nullable), with a migration
- Adding a player (single or bulk) stores `rank_tier` and `leaderboard_rank` from the OpenDota player response it already fetches
- The background profile enrichment refreshes the rank for every pool player whose `rank_fetched_at` is null or older than the enrichment cooldown (`PROFILE_ENRICHMENT_COOLDOWN_HOURS`, default 24), including players with no ingested matches
- A null rank from OpenDota is stored as null (the medal is hidden); a failed request keeps the previous rank
- A `rank_tier` outside 10–80 is stored as null

### See a Player's Medal in the Player Popup
**User story**
As a user, I want to see a player's rank medal in the player popup so that I can judge how strong they are.

**Acceptance criteria**
- `GET /players/{id}` returns `rank_tier`, `leaderboard_rank` and `rank_fetched_at`
- The popup header shows the medal badge and its name with stars (for example "Legend 4"), or "Immortal" with "#N" when there is a leaderboard place
- The text says the rank is approximate: a tooltip or note "Last known rank from OpenDota" with the date it was fetched
- A player with no rank shows no medal and no empty space
- The medal has a text equivalent for screen readers (`aria-label` or visible text)

### See the Medal on a Card
**User story**
As a player, I want to see the player's medal on a card so that I can compare my cards at a glance.

**Acceptance criteria**
- The card data used by My Team, the draw reveal and the card viewer includes the player's `rank_tier` and `leaderboard_rank`
- The card viewer shows the medal badge and name under the card image, next to the accolades (#218)
- The new card templates in #218 have a rank slot; the PNG draws the medal there and leaves it out when the rank is null
- No league name, and no image loaded from a Dota CDN

## Implementation

### Critical Files
| File | Change |
|---|---|
| `backend/models.py` | `Player.rank_tier`, `Player.leaderboard_rank`, `Player.rank_fetched_at` (Integer, nullable) |
| `backend/migrate.py` | Numbered migration adding the three columns (`PRAGMA table_info` guard) |
| `backend/player_rank.py` (new) | `parse_rank(data) -> (rank_tier, leaderboard_rank)`, `medal_name(rank_tier, leaderboard_rank) -> str \| None`; one place for the 10–80 validation and the medal names |
| `backend/enrich.py` | `enrich_players` stores the rank; `run_profile_enrichment` refreshes stale ranks for all pool players before the facts phase |
| `backend/routers/admin_players.py` | Single and bulk add store the rank from the response they already fetch |
| `backend/routers/players.py` | `GET /players/{id}` returns the rank fields |
| `backend/routers/cards.py` | Card lists (roster, reveal, card viewer) include `rank_tier`, `leaderboard_rank` |
| `frontend/app-players.js`, `frontend/index.html`, `frontend/style.css` | Medal badge (`rankMedalHtml(rankTier, leaderboardRank)`) in the popup header |
| `frontend/app-cards.js` | Medal under the card in the card viewer |
| `markdown/plans/plan-issue-218-card-formatting.md` | Rank slot in every template |
| `backend/tests/test_issue_221_player_rank_medals.py` | Parsing, storage, refresh, API, popup |

### Step 1 — Verify the OpenDota response
- Call `GET https://api.opendota.com/api/players/{account_id}` for three pool players: a ranked one, an Immortal one if any, and one with private data.
- Confirm `rank_tier` and `leaderboard_rank` are top-level fields and note their values. Record one trimmed response as a test fixture, with the account id replaced.

### Step 2 — Model, migration and parsing
- Add the three columns and the migration.
- `player_rank.py`:

```python
MEDALS = {1: "Herald", 2: "Guardian", 3: "Crusader", 4: "Archon",
          5: "Legend", 6: "Ancient", 7: "Divine", 8: "Immortal"}

def parse_rank(data: dict) -> tuple[int | None, int | None]:
    tier = data.get("rank_tier")
    if not isinstance(tier, int) or not (10 <= tier <= 80) or tier // 10 not in MEDALS:
        tier = None
    lb = data.get("leaderboard_rank")
    lb = lb if isinstance(lb, int) and lb > 0 and tier == 80 else None
    return tier, lb

def medal_name(tier, lb=None) -> str | None:
    if tier is None:
        return None
    medal, stars = MEDALS[tier // 10], tier % 10
    if medal == "Immortal":
        return f"Immortal #{lb}" if lb else "Immortal"
    return f"{medal} {stars}" if 1 <= stars <= 5 else medal
```

### Step 3 — Fetch and refresh
- `enrich_players`, `add_player` and `_bulk_add_stream` call `parse_rank(data)` on the response they already have and set `rank_fetched_at`.
- `run_profile_enrichment` gets a rank phase before the facts phase:
  - select pool players (`is_active`) whose `rank_fetched_at` is null or older than the cooldown, up to the batch size;
  - call `GET /players/{id}` through `opendota_get_json` and store the result;
  - on a failed request, leave the old values and the timestamp, so the player is retried next cycle.
- The rank phase follows the same live-match deferral as the rest of enrichment (`opendota-query-prioritization.md`).
- Count `rank_updated` in the result dict; `POST /admin/enrich-profiles` returns it too.

### Step 4 — API
- Add `rank_tier`, `leaderboard_rank` and `rank_fetched_at` to `GET /players/{id}`.
- Add `rank_tier` and `leaderboard_rank` to the card queries in `routers/cards.py` (`p.rank_tier`, `p.leaderboard_rank` in the SELECT and GROUP BY).

### Step 5 — Website
- `rankMedalHtml(tier, lb)` returns a `.rank-medal` badge:
  - a shape and colour per medal, and the stars as small marks;
  - its text: the medal name, with `title="Last known rank from OpenDota, <date>"`;
  - an empty string when `tier` is null.
- The popup header shows it next to the team name. The card viewer shows it under the card.
- Medal colours are tokens in `style.css` (`--medal-herald` … `--medal-immortal`), with text contrast of at least 4.5:1 on the modal background.

### Step 6 — Card PNG (with #218)
- Each #218 template reserves a rank slot. `image.py` gets `_draw_rank_medal(img, tier, lb, slot)`, which draws the same badge with Pillow.
- Add the slot to the #218 plan now; build it in #218.

### Step 7 — Docs and tests
- Docs: `player-profile-enrichment.md` (rank phase), `card-player-popup.md`, the feature doc, `ui_description` for the Players tab and the card viewer.
- Tests:
  - `parse_rank` and `medal_name` for 10, 54, 75, 80 with and without a leaderboard place, null, 0, 9, 81, 95 and strings;
  - the migration adds the columns;
  - add-player stores the rank from a stubbed response;
  - the enrichment refreshes only stale ranks, includes players with no matches, and keeps the old rank on a failed request;
  - `GET /players/{id}` and the card lists return the fields;
  - the popup renders the badge and hides it for null (Node harness or static check).

## Verification
- `cd backend && python -m pytest tests/test_issue_221_player_rank_medals.py tests/test_migrate.py`
- On the test server: run "Re-enrich profiles", open a few players and compare the medal with their OpenDota page.
- A player with private data shows no medal.
- An Immortal player with a leaderboard place shows "Immortal #N".
- Migration adds three nullable columns; no env vars.
