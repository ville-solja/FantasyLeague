# Card Draw Animations

On the website, a drawn card comes off a deck in the Draw panel, flies to the centre and flips face up with the rarity burst. The rest of the reveal then fades in, and on Continue the card lands in the roster slot or bench place it was added to (issue #205). A card back with a Flip control is postponed. Plan: `markdown/plans/plan-issue-205-card-draw-animations.md`. Design canvas: https://claude.ai/artifact/4xq7DmvxjpJ8m7KxfTz5uB.

---

## Draw sequence *(planned)*

1. **Stir:** the deck wobbles while `POST /draw` (or the team draw) answers and the card PNG loads and decodes, for 3 seconds at most.
2. **Lift:** the top card rises off the deck (about 220 ms).
3. **Travel:** it flies to the modal card's place while the page dims (about 460 ms).
4. **Flip:** it turns face up with a slight overshoot and the rarity burst (about 520 ms).
5. **Details:** the rarity label, destination, Reroll and Continue fade in (about 400 ms). The result is the same reveal as before.
6. **Landing:** Continue sends the card to its open roster slot, or to the front of the bench, where it glows once (about 520 ms, then a 1.2 s glow).

A failed draw plays nothing. Draw another card, ✕, Escape and the backdrop skip the landing.

## In My Team *(planned)*

- **Draw sidebar:** the sidebar starts with the deck (three stacked CSS card backs, no league name) beside a compact Chance per draw strip. The strip keeps `.rarity-grid` for the guided tour.
- **Phone:** the card flies up off the top edge, and a notice with **See roster ↑** scrolls to the roster, where the new card glows once.
- **Reduced motion:** no flight, flip, burst or landing flight. The reveal fades in and the card appears in its slot.

## Card back *(postponed)*

A Flip control in the card viewer, with a placeholder back that could later show stats or accolades. The design is on the canvas.

No endpoints, tables or env vars change.

---

*This document is a stub created at feature planning time. Fill in implementation details once the feature is built.*
