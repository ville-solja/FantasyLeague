# Plan: Card Draw Modal UX

## Context
The card draw modal currently has inconsistent interaction patterns: the Enter key does
nothing after drawing a card, the close affordances are limited to one button, and the
primary action button always says the same thing regardless of whether the user has tokens
left. These small friction points make the draw flow feel unfinished, especially when a
user wants to draw multiple cards in quick succession. This plan adds Enter-key support,
updates button labels dynamically based on remaining token count, and adds an overlay-click
dismiss so the modal can be closed in the standard web pattern. *Resolves GitHub issue #45.*

## User Stories

### Enter Key Draws or Closes the Card Modal
**User story**
As a user, I want to press Enter after drawing a card so that I can immediately draw
another card (or close the modal if I have no tokens left) without reaching for the mouse.

**Acceptance criteria**
- Pressing Enter while the card draw result modal is open triggers the same action as
  clicking the primary button
- If the user has tokens remaining, Enter draws another card
- If the user has zero tokens, Enter closes/dismisses the modal
- Enter key handling is removed when the modal is closed (no ghost listener)

### Dynamic Button Label Reflects Available Action
**User story**
As a user, I want the primary button in the draw modal to tell me what will happen next so
that I understand whether clicking it costs a token or just dismisses the screen.

**Acceptance criteria**
- When the user has 1 or more tokens after drawing, the primary button reads "Draw another card"
- When the user has 0 tokens after drawing, the primary button reads "Continue"
- The button label updates immediately after each draw without a page reload

### Dismiss Modal by Clicking Outside
**User story**
As a user, I want to close the card draw modal by clicking outside it (on the dark
overlay) so that I can dismiss it using the standard web pattern instead of hunting for
the X button.

**Acceptance criteria**
- Clicking the modal backdrop (outside the modal content box) closes the modal
- Clicking inside the modal content does not close it (click propagation stops at the
  content box)
- The modal can still be closed with the existing X button as well

---

## Implementation

### Critical Files
| File | Change |
|---|---|
| `frontend/app-cards.js` | Dynamic button label, Enter key handler, backdrop click dismiss |
| `frontend/index.html` | Ensure the draw modal backdrop is a distinct element that can receive click events; add `id` or class if needed |

### Step 1 — Identify the draw modal structure
Read `frontend/index.html` and locate the card draw result modal. Note the IDs of:
- The modal wrapper / backdrop element
- The modal content box
- The primary action button
- The token balance display

Read `frontend/app-cards.js` and locate the `drawCard()` (or equivalent) function and
the modal show/hide logic.

### Step 2 — Dynamic button label
After each draw, read the current token balance (already fetched and displayed) and set
the primary button's `textContent`:
```js
drawActionBtn.textContent = currentTokens > 0 ? "Draw another card" : "Continue";
```
Call this any time the modal is shown or after a draw completes.

### Step 3 — Enter key handler
Add a `keydown` listener on `document` when the modal opens; remove it when the modal
closes. Handler:
```js
function _onDrawModalKey(e) {
  if (e.key !== "Enter") return;
  e.preventDefault();
  drawActionBtn.click();   // reuses existing button logic — draws or closes
}
document.addEventListener("keydown", _onDrawModalKey);
// ... on modal close:
document.removeEventListener("keydown", _onDrawModalKey);
```

### Step 4 — Backdrop click dismiss
The modal backdrop must be a separate element that wraps (but is not) the content box.
Add a click listener to the backdrop that closes the modal, and `stopPropagation()` on
the content box so inner clicks don't bubble:
```js
modalBackdrop.addEventListener("click", closeDrawModal);
modalContent.addEventListener("click", e => e.stopPropagation());
```
If the HTML structure does not already separate backdrop from content, add a wrapper div
in `index.html`.

---

## Verification
- Draw a card → modal shows with "Draw another card" button → press Enter → draws another card
- Draw until 0 tokens → button reads "Continue" → press Enter → modal closes
- Draw a card → click the dark area outside the modal → modal closes
- Draw a card → click inside the modal content → modal stays open
- Open modal → press Escape or click X → modal closes (existing behaviour unchanged)
- Rapid Enter presses do not submit multiple draws in a single keydown event (check
  `preventDefault` is present)
