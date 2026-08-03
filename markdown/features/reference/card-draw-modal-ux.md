# Card Draw Modal UX

Interaction improvements to the card draw result modal: Enter-key support, a dynamic
primary button label, and backdrop-click dismissal.

---

## Interactions

### Enter key
When the draw result modal is open, pressing Enter fires the same action as the primary
button — draws another card if tokens remain, or closes the modal if the token balance is
zero. The listener is attached on modal open and removed on close so it does not interfere
with other keyboard interactions.

### Dynamic button label
The primary action button reads:
- **"Draw another card"** — when the user still has tokens after the current draw
- **"Continue"** — when the token balance reaches zero

The label is set after each draw response, before the user can interact with the button.

### Backdrop click dismiss
Clicking the dark overlay area surrounding the modal content closes the modal. Clicks
inside the content box are stopped with `stopPropagation()` so they do not bubble to the
backdrop. The existing X-button close path is unchanged.
