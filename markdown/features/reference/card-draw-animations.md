# Card Draw Animations

When a player draws a card on the website, it comes off a visible deck in the Draw panel, flies to the centre, flips face up with the rarity burst, and then the rest of the reveal fades in. Any card shown in the card viewer can be flipped to its back, which is a placeholder for now (issue #205). Plan: `markdown/plans/plan-issue-205-card-draw-animations.md`. Design canvas: https://claude.ai/artifact/4xq7DmvxjpJ8m7KxfTz5uB.

---

## Draw sequence *(planned)*

1. **Stir:** the deck wobbles while `POST /draw` (or the team draw) answers and the card PNG loads and decodes, for 3 seconds at most.
2. **Lift:** the top card rises off the deck (about 220 ms).
3. **Travel:** it flies to the modal card's place while the page dims (about 460 ms).
4. **Flip:** it turns face up with a slight overshoot and the rarity burst (about 520 ms).
5. **Details:** the rarity label, destination, Reroll and Continue fade in (about 400 ms). The result is the same reveal as before.

A failed draw plays nothing. With reduced motion, the finished reveal fades in without flight, flip or burst.

## Card back *(planned)*

A **Flip card** button, or a click on the card image, turns the card in the viewer to its back. The back is CSS only (brand pattern and emblem, no league name) and shares its style with the deck. Every card opens front side up. Stats or accolades on the back are a later step.

No endpoints, tables or env vars change.

---

*This document is a stub created at feature planning time. Fill in implementation details once the feature is built.*
