# Plan: Remove Card Move / Bench-Activate Buttons from My Team

## Context
GitHub issue #93 asks to remove the ◀/▶ move-left/move-right buttons and the Bench/Activate
text buttons from card slots in the My Team tab, leaving drag-and-drop as the primary (visually
uncluttered) way to manage the roster. Both button pairs currently render in every unlocked
card slot (`_cardSlotHTML()` in `frontend/app-roster.js`).

**Accessibility tradeoff, resolved with the user before drafting this plan:** the ◀/▶ buttons
were added in the immediately preceding session specifically to give keyboard-only and
non-drag-touch users a way to reorder cards, and the Bench/Activate buttons are the *only*
existing way to move a card between zones without dragging. Removing all four with no
replacement would leave keyboard-only users with no way to activate or bench a card at all. The
user was asked directly and chose: remove all four visible buttons, but keep a keyboard-only
fallback — focusing a card and pressing Enter or Space toggles it between bench and active,
reusing the existing `activateCard()`/`deactivateCard()` functions (and therefore their
existing error handling: roster-full, duplicate-player-active, etc.). In-zone reordering
(the ◀/▶ buttons' specific function) has no keyboard fallback in this plan — after this change
it is drag-and-drop only, which is an explicit, disclosed part of the user's chosen scope, not
an oversight.

One consequence worth flagging in the plan itself: the card image's Enter/Space keyboard
handler currently opens the card detail modal (`showRosterCard()`, added in the same prior
session). This plan repurposes Enter/Space on a roster card image to toggle bench/active
instead, so keyboard users lose the ability to open the detail modal via keyboard on that
element — mouse click continues to open it, unchanged. No new key binding is introduced to
recover this, since it was outside the explicit scope the user confirmed; note it in the
feature doc as a known, accepted limitation rather than silently dropping it undocumented.

Because `reference/my-team-drag-and-drop.md` already documents this exact card-slot area, it is
**updated in place** rather than duplicated into a new stub, per the project's "do not duplicate
documentation" rule.

Resolves GitHub issue #93.

## User Stories

### Decluttered Card Slot Controls
**User story**
As a player, I want the My Team card slots to show only the card itself (no move or
bench/activate buttons) so that the roster view stays visually clean and drag-and-drop is the
obvious, primary way to manage my lineup.

**Acceptance criteria**
- The ◀/▶ move-left/move-right buttons are removed from every card slot (active and bench)
- The Bench/Activate text buttons are removed from every card slot
- Card slots show only the card image, its points value, and modifier pills (if any);
  drag-and-drop remains the way to reorder within a zone or move a card between zones by mouse
- Locked-week card slots are unaffected (they never showed these buttons)

---

### Keyboard Fallback for Bench/Active Toggle
**User story**
As a keyboard-only user, I want to move a card between my bench and active roster without a
mouse, so that removing the visible Bench/Activate buttons doesn't lock me out of that action
entirely.

**Acceptance criteria**
- Focusing a card slot's image and pressing Enter or Space toggles the card between active and
  bench: an active card is benched, a benched card is activated
- Activation failure cases reuse the existing `activateCard()` error handling (e.g. roster full,
  a card for this player is already active) — no new error copy is introduced
- The toggle does nothing when the current week is locked, matching drag-and-drop's existing
  lock gating (`_rosterLocked`)
- Mouse click on the card image continues to open the card detail modal, unchanged; this is a
  distinct interaction from the new keyboard toggle, not a replacement for it

## Implementation

### Critical Files
| File | Change |
|---|---|
| `frontend/app-roster.js` | `_cardSlotHTML()`: remove the `actionBtn`/`moveBtns` markup and the `.card-slot-actions` wrapper. Remove the now-dead `moveCardInZone()` helper (nothing calls it after the ◀/▶ buttons are removed, and no keyboard replacement is in scope). Change the card image's `onkeydown` handler from opening the detail modal to calling a new `toggleCardZone(cardId, isActiveCard)` function |
| `frontend/style.css` | Remove `.card-slot-actions`, `.card-slot-btn`, `.card-slot-btn--move` rules (including their mobile breakpoint overrides) if nothing else references them after this change — verify via grep before deleting |
| `markdown/features/reference/my-team-drag-and-drop.md` | Update in place: document that button-based controls were removed, drag-and-drop is now the only mouse-based way to move cards, and describe the Enter/Space keyboard toggle as the accessible fallback (including the note that this superseded keyboard-triggered detail-modal opening on the same element) |

### Step 1 — Remove the visible buttons
In `_cardSlotHTML()`, delete the `actionBtn` construction (Bench/Activate `<button>`), the
`moveBtns` construction (◀/▶ `<button>`s), and the `<div class="card-slot-actions">` wrapper
that rendered them. Keep `.card-slot-pts` and `.card-slot-mods` (modifier pills) as-is.

### Step 2 — Remove now-dead code
Delete `moveCardInZone(cardId, direction)` — no caller remains once the ◀/▶ buttons are gone,
and this plan's confirmed scope does not add a keyboard equivalent for in-zone reordering.

### Step 3 — Keyboard bench/active toggle
Add a new function reusing the existing activate/deactivate machinery:
```js
async function toggleCardZone(cardId, isActiveCard) {
  if (isActiveCard) {
    await deactivateCard(cardId);
  } else {
    await activateCard(cardId);
  }
}
```
Update the card image's `onkeydown` in `_cardSlotHTML()` from calling `showRosterCard(cardId)`
to calling `toggleCardZone(cardId, isActiveCard)` on Enter/Space, gated on `!_rosterLocked` (the
image is only rendered with a live keydown path when the week is unlocked — verify this matches
existing lock-gating exactly rather than assuming). `isActiveCard` is already knowable at
render time from the same `action`/`zone` logic `_cardSlotHTML()` already computes.

### Step 4 — Documentation
Update `reference/my-team-drag-and-drop.md`: add a short section describing that the button
controls were removed (issue #93) in favor of drag-and-drop plus a keyboard Enter/Space toggle,
and note the accepted limitation that keyboard-triggered detail-modal viewing no longer exists
on the card image (mouse click still works). No story file needs a "superseded" annotation —
the ◀/▶ buttons and Bench/Activate buttons were never formalized as their own user stories, so
there is nothing stale to mark.

## Verification
- My Team tab, unlocked week: no ◀/▶ or Bench/Activate buttons visible on any card slot
- Tab to an active card's image, press Enter or Space: card moves to bench, roster re-renders,
  no page refresh needed
- Tab to a bench card's image, press Enter or Space: card activates if room exists; if the
  roster is full or the same player is already active, the existing error message from
  `activateCard()` is shown, matching current button-driven behavior exactly
- Mouse click on any card image still opens the card detail modal
- Drag-and-drop still fully works: in-zone reorder and cross-zone moves, exactly as before this
  change (`reference/my-team-drag-and-drop.md`'s existing Drag Scenarios table is unaffected)
- Locked week: Enter/Space on a card does nothing, matching drag-and-drop's existing disabled
  state
- No backend change, no migration — this is a frontend-only change
