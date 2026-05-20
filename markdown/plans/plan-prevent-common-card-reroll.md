# Plan: Prevent Common Card Reroll

## Context
Common cards have no card modifiers — the modifier slots are empty by design — so allowing
them to be rerolled gives the user nothing in return for their token. Users can accidentally
spend a token on a common reroll without realising it does nothing. The fix is a two-layer
guard: the backend rejects the request with a 400 so the rule cannot be bypassed, and the
frontend hides the Reroll button entirely on common cards so the option is never presented
to the user. *Resolves GitHub issue #58.*

## User Stories

### Reroll Button Hidden for Common Cards
**User story**
As a user, I want the Reroll Modifiers button to be absent when I am viewing a common card
so that I am not tempted to spend a token on an action that does nothing.

**Acceptance criteria**
- The Reroll Modifiers button is not visible when the card draw modal shows a common card
- The Reroll Modifiers button is visible for rare, epic, and legendary cards (unchanged)
- No change to any other modal behaviour

### Backend Rejects Common Card Reroll
**User story**
As a developer, I want the reroll endpoint to reject requests for common cards so that the
rule is enforced server-side regardless of how the request is made.

**Acceptance criteria**
- `POST /roster/{card_id}/reroll` returns HTTP 400 with a clear error message when the
  target card is of type `"common"`
- The endpoint continues to succeed for rare, epic, and legendary cards
- The error message is distinct enough to aid debugging (e.g. `"Common cards cannot be rerolled"`)

---

## Implementation

### Critical Files
| File | Change |
|---|---|
| `backend/routers/cards.py` (or wherever `/roster/{card_id}/reroll` lives) | Add `card_type == "common"` guard before processing the reroll |
| `frontend/app-cards.js` | Hide `rerollBtn` when `card.card_type === "common"` in `showCard()` |

### Step 1 — Locate the reroll endpoint
Find the `POST /roster/{card_id}/reroll` handler. Read the surrounding code to understand
how the card object is fetched and how the response is structured.

### Step 2 — Backend guard
Add a check immediately after fetching the card, before any token deduction or modifier
change:

```python
if card.card_type == "common":
    raise HTTPException(status_code=400, detail="Common cards cannot be rerolled")
```

### Step 3 — Frontend: hide reroll button for common cards
In `showCard()` in `frontend/app-cards.js`, the reroll button visibility is already
controlled. Extend the existing logic to also hide the button entirely for common cards:

```js
const rerollBtn = document.getElementById("rerollBtn");
if (rerollBtn) {
  const isCommon = (card.card_type || "").toLowerCase() === "common";
  rerollBtn.style.display = isCommon ? "none" : "";
  // existing token-balance enable/disable logic unchanged for non-common cards
  if (!isCommon) {
    const hasTokens = _tokenBalance !== null && _tokenBalance >= 1;
    rerollBtn.disabled = !hasTokens;
    rerollBtn.style.opacity = hasTokens ? "1" : "0.4";
    rerollBtn.style.cursor = hasTokens ? "pointer" : "not-allowed";
  }
}
```

---

## Verification
- Draw or view a common card → Reroll Modifiers button is not visible
- Draw or view a rare/epic/legendary card → Reroll Modifiers button is visible as before
- Attempt `POST /roster/{common_card_id}/reroll` directly → HTTP 400 with
  `"Common cards cannot be rerolled"`
- Reroll a rare/epic/legendary card with tokens → succeeds as before
- Token balance is unchanged after a rejected common reroll attempt
