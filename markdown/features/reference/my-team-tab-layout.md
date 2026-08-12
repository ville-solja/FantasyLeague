# My Team Tab Layout

The My Team tab layout places the roster as the dominant content area with draw controls in a compact right sidebar, so users reach their lineup immediately without scrolling.

---

## Layout structure

On desktop (≥ 768 px) the tab uses a two-column CSS grid: the **My Roster** panel occupies the main column (`1fr`) and the **Draw sidebar** occupies a fixed-width right column (~300 px).

On mobile (< 768 px) the grid collapses to a single column — roster first, then the draw sidebar below.

## My Roster (main column)

Contains the week selector, active card grid, weekly and season point totals, and the bench. This is the primary interaction area of the tab.

## Draw sidebar (right column)

Renamed from "Deck" to "Draw" — see `reference/draw-panel-redesign.md`. There is no shared,
finite card pool; cards are generated per draw (`reference/dynamic-card-creation.md`). Contains
(top to bottom):
- Per-rarity drop-rate percentages (Common / Rare / Epic / Legendary), sourced live from
  `GET /config`'s `draw_rates` — not a count of anything remaining
- "Draw a card" button + token balance (`#drawCounter`)
- "Draw Booster from Team" button, opening the team-booster modal (`reference/team-booster-draws.md`)
- Promo code redemption field
- Scoring info toggle (collapsible)

## Endpoints

No new endpoints. Layout change is purely frontend.
