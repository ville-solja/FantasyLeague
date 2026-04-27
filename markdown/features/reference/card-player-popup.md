# Card Player Popup Navigation

Makes the player name shown on a viewed card clickable, opening the player detail popup, and ensures the card remains visible when the popup is closed.

---

## Flow

1. User clicks a card image in My Team → card opens in the reveal modal (`#revealModal`)
2. Player name in the reveal modal is rendered as an `entity-link` (when `player_id` is present)
3. User clicks the player name → `openPlayerModal(player_id)` opens `#playerModal` on top
4. User closes the player modal (button or Escape) → reveal modal remains open and unchanged

## Implementation

| File | Change |
|---|---|
| `frontend/app.js` — `showCard()` | `#revealPlayer` rendered as `entity-link` when `card.player_id` present; plain text during draw animation or when no player |
| `frontend/app.js` — Escape handler | `keydown` listener closes top-most open modal: `playerModal` → `teamModal` → `revealModal` |
| `backend/main.py` — draw response | Added `player_id` field to the `POST /draw` response so newly drawn cards also get the clickable name |

---

*This document is a stub created at feature planning time. Fill in implementation details once the feature is built.*
