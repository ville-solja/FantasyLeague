# Plan: Accolades and Rank in the Player Popup

## Context
#228 took the accolade and tag symbols off the card face. The card viewer (`#revealModal`) now shows three things under the card:
- the rank medal (`#revealRank`, #221);
- a Tags section (`#revealTags`);
- an Accolades section with details (`#revealAccolades`, `accoladeDetailsHtml`: champion team, point values, seasons played).

Issue #230 asks to remove the accolades and the rank from the card popup, and show them as statistics in the player popup for now.

**What the player popup has today:**
- the rank medal next to the team name in the header (`rankMedalHtml` in `openPlayerModal`);
- tag and accolade pips in the header (`#playerModalPips`);
- an Accolades section (`renderPlayerAccolades`, #50): a Holo banner, three tiles (Champion titles, Season awards, Seasons played), and a timeline by season built from chips, whose details are only in hover titles;
- the summary tiles (`_popupTilesHtml`, #208): Matches, Avg pts, Total pts, Best match, MVPs.

**Decisions** (change them in review if needed):
- **Card viewer:**
  - The rank medal and the Accolades section are removed (`#revealRank`, `#revealAccolades`, `_renderRevealRank`, the accolade half of `_renderCardAccolades`).
  - The **Tags** section stays, still shown after the flip on a draw.
  - The player's name under the card already opens the player popup (`openPlayerModal`). It gets a visible hint, "Stats and accolades", so players know where the accolades went.
- **Rank as a statistic:**
  - The rank becomes a summary tile in the player popup: the medal symbol and name ("Legend 4", "Immortal #120") as the value, labelled "Rank", with "OpenDota, <date>" underneath (from `rank_fetched_at`).
  - It sits after MVPs. Unranked players get no tile.
  - The header medal is removed so the rank shows once.
- **Accolades as statistics:**
  - The popup's Accolades section keeps its Holo banner and its three tiles.
  - Its season timeline uses the detail lines from #228 instead of chips: "S15 Div 1 Champion · with Team Name", "S15 Most Points · 812.3 pts".
  - Seasons played stays a tile, with a one-line summary "Played 7 seasons · S4–S16" (counted from Season 4) and its per-season list behind a disclosure.
  - The header pips stay as the at-a-glance summary.
- **One helper:** `accoladeDetailsHtml` is reused, with the season grouping done by the popup. It has no other caller left, so its Played summary may move into the popup code if that's simpler.
- **No backend change:** the card endpoints keep returning `rank_tier` and `leaderboard_rank`, because My Team's data and other callers may read them. `GET /players/{id}` already returns the rank and the accolades.

Resolves GitHub issue #230.

## User Stories

### The Card Popup Shows the Card
**User story**
As a player, I want the card popup to show the card without the player's statistics, so that it stays about the card.

**Acceptance criteria**
- **Removed:** the card viewer shows no rank medal and no Accolades section, both when opening a card and after a draw.
- **Tags stay:** the Tags section still shows for a player with tags, after the flip on a draw.
- **Way on:** the player's name under the card opens the player popup and carries the hint "Stats and accolades".
- **No dead code:** `_renderRevealRank`, `#revealRank`, `#revealAccolades` and their CSS are removed.

### Rank as a Player Statistic
**User story**
As a player, I want a player's rank shown with their other statistics, so that I can compare it with how they score.

**Acceptance criteria**
- **Tile:** the player popup's summary tiles end with a **Rank** tile: the medal symbol and its name ("Legend 4", or "Immortal #120" with a leaderboard place), and "OpenDota, <date>" underneath.
- **Unranked:** a player with no `rank_tier` shows no Rank tile and no empty space.
- **Once:** the header no longer shows the medal.
- **Accessible:** the tile's text carries the rank; the medal symbol is decorative.

### Accolades as Player Statistics
**User story**
As a player, I want a player's accolades listed with their details in the player popup, so that I can see what they won, when and with which team.

**Acceptance criteria**
- **Section:** the Accolades section keeps the Holo banner and the Champion titles, Season awards and Seasons played tiles.
- **Timeline:**
  - one entry per season, newest first, each listing that season's accolades as detail lines;
  - champion lines name the team ("S15 Div 1 Champion · with Team Name"), and point-based accolades show their value ("S15 Most Points · 812.3 pts").
- **Seasons played:** a line "Played 7 seasons · S4–S16" with the per-season list (and the live season's match count) behind a disclosure.
- **Empty:** a player with no accolades shows no section, as today.
- **Phone width:** no sideways scroll.

## Implementation

### Critical Files
| File | Change |
|---|---|
| `frontend/app-cards.js` | Remove `_renderRevealRank` and the Accolades section; keep Tags; add the "Stats and accolades" hint on the name |
| `frontend/index.html` | Remove `#revealRank` and `#revealAccolades` |
| `frontend/app-player-popup.js` | Rank tile in `_popupTilesHtml`; header medal removed; `renderPlayerAccolades` timeline as detail lines with the Played summary and disclosure |
| `frontend/app-globals.js` | `accoladeDetailsHtml` reused or folded into the popup; `rankMedalHtml` gets a tile form (or the tile reuses its markup) |
| `frontend/style.css` | Remove the card viewer rank and accolades styles; Rank tile and timeline line styles (tokens only, before GUIDED TOUR) |
| `backend/tests/test_issue_230_accolades_and_rank_in_player_popup.py` | Tests |
| `backend/tests/test_issue_228_card_visuals_rollback.py`, `backend/tests/test_issue_221_player_rank_medals.py`, `backend/tests/test_issue_50_season_winners_and_holo_cards.py` | Card viewer accolade and rank assertions now check their absence; popup assertions follow the new layout |
| `markdown/features/reference/player-popup-accolades-and-rank.md`, `card-visuals-rollback.md`, `player-rank-medals.md`, `season-winners-and-holo-cards.md`, `markdown/ui_description/README.md` (card reveal modal), the player popup UI spec, `markdown/stories/leaderboard.md` | Docs |

No migration, no new env var, no backend change.

### Step 1 — Card viewer
Remove the rank and the Accolades section, keep Tags, and add the hint on the name.

### Step 2 — Rank tile
Add the tile to `_popupTilesHtml` from `p.rank_tier`, `p.leaderboard_rank` and `p.rank_fetched_at`, and drop the header medal.

### Step 3 — Accolades timeline
Replace the chip timeline with detail lines and add the Played summary with its disclosure.

### Step 4 — Tests and docs
**Tests:**
- the card viewer has no rank or Accolades section (source and harness), and Tags still shows after the flip;
- the name carries the hint and opens the player popup;
- Rank tile: medal name, Immortal place, date line, no tile when unranked, no header medal;
- timeline detail lines: order, champion team, points, Played summary and disclosure, the live season's matches, empty state;
- CSS before GUIDED TOUR, tokens only.

## Verification
- **Card viewer:** opening a champion's card shows the card, the Tags section if any, and the name hint, with no rank or accolades.
- **Player popup:** the same player shows a Rank tile ("Legend 4", "OpenDota, <date>"), and the Accolades timeline shows "S15 Div 1 Champion · with <team>".
- **Unranked player:** no Rank tile.
- **Phone width:** tiles and timeline wrap without sideways scroll.
