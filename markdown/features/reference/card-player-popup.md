# Card Player Popup Navigation

Makes the player name shown on a viewed card clickable, opening the player detail popup, and ensures the card remains visible when the popup is closed.

---

## Flow

1. User clicks a card image in My Team → card opens in the reveal modal (`#revealModal`)
2. Player name in the reveal modal is rendered as an `entity-link` (when `player_id` is present)
3. User clicks the player name → `openPlayerModal(player_id)` opens `#playerModal` on top
4. User closes the player modal (button or Escape) → reveal modal remains open and unchanged

The player name carries the hint "Stats and accolades" (issue #230): the card viewer shows no rank medal and no accolades. The player popup shows them, the rank as its last summary tile (see `player-popup-accolades-and-rank.md` and `player-rank-medals.md`). Unranked players get no Rank tile.

## Implementation

| File | Change |
|---|---|
| `frontend/app-cards.js` — `showCard()` | `#revealPlayer` rendered as `entity-link` when `card.player_id` present; plain text during draw animation or when no player |
| `frontend/app-init.js` — Escape handler | `keydown` listener closes top-most open modal: `playerModal` → `teamModal` → `revealModal` |
| `backend/routers/cards.py` — draw response | Added `player_id` field to the `POST /draw` response so newly drawn cards also get the clickable name |
| `frontend/app-cards.js` — `showCard()` | The name link contains a `.reveal-player-hint` line, "Stats and accolades" (issue #230) |
| `frontend/app-player-popup.js` — `_popupRankTile()` | The Rank summary tile, `rankMedalHtml(p.rank_tier, p.leaderboard_rank)` with "OpenDota, <date>" (issue #230; it replaced the header medal and `_renderRevealRank`) |
