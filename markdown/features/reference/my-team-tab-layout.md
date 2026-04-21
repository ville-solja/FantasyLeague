# My Team Tab Layout

The My Team tab layout places the roster as the dominant content area with deck controls in a compact right sidebar, so users reach their lineup immediately without scrolling.

---

## Layout structure

On desktop (≥ 768 px) the tab uses a two-column CSS grid: the **My Roster** panel occupies the main column (`1fr`) and the **Deck sidebar** occupies a fixed-width right column (~300 px).

On mobile (< 768 px) the grid collapses to a single column — roster first, then the deck sidebar below.

## My Roster (main column)

Contains the week selector, active card grid, weekly and season point totals, and the bench. This is the primary interaction area of the tab.

## Deck sidebar (right column)

Contains (top to bottom):
- Rarity counts (Common / Rare / Epic / Legendary remaining in the shared deck)
- Draw a card button + token balance
- Promo code redemption field
- Scoring info toggle (collapsible)

## Endpoints

No new endpoints. Layout change is purely frontend.

---

*This document is a stub created at feature planning time. Fill in implementation details once the feature is built.*
