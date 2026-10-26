# Accolades and Rank in the Player Popup

The player's rank and accolades are statistics in the player popup, not part of the card popup. Plan: `markdown/plans/plan-issue-230-accolades-and-rank-in-player-popup.md` (issue #230). Frontend only: no endpoint, schema or env change.

---

## Card viewer

The card viewer (`#revealModal`) shows the card, the player's name and team, and the **Tags** section (#228). It shows no rank medal and no Accolades section, both when a card is opened and after a draw.

- **Tags:** `_renderRevealTags(card, drawFx)` in `app-cards.js` fills `#revealTags` from `tagDetailsHtml(playerTags(card.player_id))`. The section is hidden when empty. On a draw it stays hidden until the flip has finished (`_showRevealTags`).
- **Name hint:** when the card has a `player_id` and isn't a draw, the name under the card is a focusable button (`entity-link`, `role="button"`, `tabindex` 0). Click, Enter or Space opens `openPlayerModal(card.player_id)`. Inside it, a `.reveal-player-hint` line reads "Stats and accolades". A card without a `player_id` shows the plain name, with no hint and no link. On a draw the names are painted on the PNG, so the draw reveal shows neither the name nor the hint.
- **Removed:** `#revealRank`, `#revealAccolades`, `_renderRevealRank`, the `.reveal-rank` rules and `accoladeDetailsHtml`. `_renderCardAccolades` and `_showRevealSections` became `_renderRevealTags` and `_showRevealTags`.

## Player popup

### Rank tile

- **Position:** the last summary tile, after MVPs (`_popupRankTile(p)` in `app-player-popup.js`, called by `_popupTilesHtml`).
- **Value:** `rankMedalHtml(p.rank_tier, p.leaderboard_rank)`, the medal symbol and its name: "Legend 4" with ★ stars, "Immortal", or "Immortal #120".
- **Label and sub line:** labelled "Rank", with "OpenDota, <date>" underneath. The date comes from `rank_fetched_at` and uses the popup's date format (`_popupDate`). Without a valid timestamp the line reads "OpenDota".
- **Unranked:** a player with no `rank_tier` (null, 0, missing or out of range) gets no tile, and the grid keeps its five-tile layout.
- **Layout:** with the Rank tile the grid is `.player-popup-tiles--ranked`, two rows of three. At phone width (640 px and below) it shows two columns. The medal wraps inside the tile (`.player-modal-stat--rank .rank-medal`).
- **Accessibility:** the medal name is visible text. The symbol and the stars are `aria-hidden`.
- **Header:** the medal is no longer shown next to the team name, so the rank appears once.

`rankMedalHtml(tier, lb)` in `app-globals.js` is now the tile form only. It has no `role="img"`, `aria-label` or title, and no `fetchedAt` argument. A non-numeric tier gives `""`, and a non-numeric leaderboard place is ignored.

### Accolades section

`renderPlayerAccolades(p)` keeps the header pips (`#playerModalPips`: tag pips, then accolade pips), the "Holo unlocked" banner and the three tiles: Champion titles, Season awards and Seasons played. Under the tiles it shows:

- **Played summary:**
  - The summary line is built by `accoladePlayedLine(accolades, {season, matches})`: "Played 7 seasons · S4–S16", or "Played 1 season · S16". It counts from Season 4, as issue #212 does (`ACCOLADE_PLAYED_FROM`).
  - The seasons sit in a closed `<details>`, newest first. The live season (`current_season`) shows its match count, for example "S16 · 5 matches".
  - The Seasons played tile shows the same count (`accoladePlayedSeasons`), counted from Season 4 (`ACCOLADE_PLAYED_FROM`). Before #230 the tile counted every Played accolade. The header's "N seasons played" still comes from the backend (`p.seasons_played`, every Played accolade), so the two differ only if an admin records a Played accolade for a season before Season 4.
- **Timeline** (`ol.player-accolades-timeline`):
  - One entry per season, newest first. Each entry lists that season's accolades as detail lines built by `accoladeDetailLine(a)`, champions first: "S15 Div 1 Champion · with Team Name", "S15 Most Points · 812.3 pts".
  - A champion with no team name reads "S15 Div 1 Champion". Played rows are not timeline entries.
  - Team names are escaped. Lines use the `.card-detail` markup from #228 (the "card" prefix is historical: it is now the shared detail-line style, used in the card viewer Tags section and here), with the kind's pip as a decorative symbol.
- **Empty:** a player with no accolades gets no section, as before.

`accoladeChipsHtml` is no longer used by the popup. Player management, the Teams tab, the team popup and History still use it.

## CSS

The rules live in `style.css`, before the GUIDED TOUR section, and use design-system tokens only:

- `.reveal-player-hint`, after `.reveal-card .player-name`;
- `.player-accolades-played`, `.player-accolades-timeline` and `.player-accolades-season` in the player popup accolades block;
- `.player-popup-tiles--ranked`, next to `.player-popup-tiles` and in the 640 px media query;
- `.player-modal-stat--rank .rank-medal`, in the RANK MEDAL block.

The season label column (`.player-accolades-season-label`) was removed, because every line already starts with its season.

## Backend

There is no backend change. The card endpoints still return `rank_tier` and `leaderboard_rank`, and `GET /players/{id}` returns `rank_tier`, `leaderboard_rank`, `rank_fetched_at`, the accolades, `current_season` and `current_season_matches`.

## Tests

`backend/tests/test_issue_230_accolades_and_rank_in_player_popup.py` covers the card viewer through the #205 draw harness, and the Rank tile, the header and the Accolades section through the #208 popup harness. It also checks CSS placement, tokens and phone-width wrapping. The tests for #221, #228, #50 and #217 now check that the card viewer has no rank or accolades, and follow the new popup layout.
