# Plan: Card Player Popup Navigation

## Context

When a user views a card in the reveal modal (either after drawing or by clicking a card in My Team), the player name is displayed as plain text with no click handler. There is no way to open the player bio/stats popup from within the card view. Additionally, if the user navigates to the player popup from an adjacent surface and then closes it, the card modal is dismissed along with it. This feature makes the player name on a viewed card a direct entry point to the player popup, and ensures closing the player popup returns focus to the card rather than losing it.

---

## User Stories

### 18.1 Open Player Popup from Card Name
**User story**
As a user, I want to click the player name displayed on a viewed card so that I can read the player's stats and bio without navigating away from the card.

**Acceptance criteria**
- The player name shown in the card reveal modal (`#revealPlayer`) is rendered as a clickable link when a valid player exists
- Clicking it opens the player detail modal (`#playerModal`) with the correct player loaded
- The reveal modal remains open and visible behind the player modal
- Cards without a linked player (e.g. team-type cards) show the name as non-clickable plain text

### 18.2 Return to Card after Closing Player Popup
**User story**
As a user, I want the card to still be showing when I close the player popup so that I can continue viewing or managing the card I was looking at.

**Acceptance criteria**
- Closing the player modal (via the close button or overlay click) leaves the reveal modal open and unchanged
- The player name in the reveal modal is still rendered as a clickable link after the player modal is closed
- Pressing Escape closes only the top-most open modal (player popup first, then card reveal if pressed again)

---

## Implementation

### Critical Files

| File | Change |
|---|---|
| `frontend/app.js` | Make `#revealPlayer` a link when `player_id` is present; add `player_id` to `showCard` call path; fix modal stacking / Escape key handling |
| `frontend/index.html` | Change `#revealPlayer` from `<div>` to `<span>` or add inner `<span>` for the link; no structural change required if done in JS |

### Step 1 — Thread `player_id` through the card data

The `showCard(card, footer, opts)` function already receives the full card object. Confirm that `card.player_id` (or equivalent FK field) is present on roster card objects. If not, add it to the `/roster` response in `backend/main.py`.

### Step 2 — Render player name as a link in `showCard`

Replace the plain `.textContent` assignment for `#revealPlayer`:

```js
const playerNameEl = document.getElementById("revealPlayer");
if (card.player_id && !drawFx) {
  playerNameEl.innerHTML =
    `<span class="entity-link" onclick="openPlayerModal(${card.player_id})">${card.player_name || ""}</span>`;
} else {
  playerNameEl.textContent = drawFx ? "" : (card.player_name || "");
}
```

### Step 3 — Ensure reveal modal stays open when player modal opens

`openPlayerModal` currently opens `#playerModal` without closing `#revealModal`. Verify no shared overlay or Escape handler triggers `closeReveal()` when the player modal is open.

If a single `keydown` Escape handler exists, update it to close only the top-most visible modal:

```js
document.addEventListener("keydown", e => {
  if (e.key !== "Escape") return;
  if (!document.getElementById("playerModal").classList.contains("hidden")) {
    closePlayerModal(); return;
  }
  if (!document.getElementById("revealModal").classList.contains("hidden")) {
    closeReveal(); return;
  }
  // … other modals
});
```

### Step 4 — (Optional) Player name below card slot in My Team

If a player name label below the card image in `_cardSlotHTML` is desired, add it as a clickable span:

```js
const nameLink = c.player_id
  ? `<div class="card-slot-name"><span class="entity-link" onclick="showRosterCard(${c.id})">${c.player_name}</span></div>`
  : "";
```

This is out of scope for the core issue but is a natural follow-on.

---

## Verification

- Draw or view a card in the reveal modal → player name is underlined / styled as a link
- Click the player name → player modal opens on top; reveal modal still visible behind it
- Close player modal via button → reveal modal still showing the same card
- Close player modal via overlay click → reveal modal still visible
- Press Escape with both modals open → player modal closes first; second Escape closes reveal modal
- View a card that has no linked player → name shown as plain text, no crash
