# 18. Card Player Popup Navigation

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
