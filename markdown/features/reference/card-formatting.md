# Card Formatting

A new card layout that gives accolades (user tags such as Caster and Season Winner) their own place on the card PNG, with labels in the card viewer (issue #218). Plan: `markdown/plans/plan-issue-218-card-formatting.md`. Design canvas with six portrait and three landscape layouts and an accolade kit: https://claude.ai/artifact/7EZ3WKh3GrN63FipYATfG8.

---

## Layout

*(planned)* The chosen layout replaces today's composition in `backend/image.py` (see [Card Image Generation](card-image-generation.md)). The canvas size stays 597 × 845 for a portrait layout; a landscape layout (845 × 597) also changes the frontend card sizes. Rarity is shown by a label, stars or a gem as well as colour. Team logos (cached at 250 × 150) sit on a 5:3 plate instead of a squashed circle; the 184 × 184 avatar is enlarged at most about 2×, with a blurred backdrop for larger areas.

## Accolades

*(planned)* The tags of the user linked to the card's player are drawn in the layout's accolade area, using `assets/stickers/{key}.png` as each icon. Past the layout's maximum, the last place shows "+N". A tag without a sticker gets a letter badge. The card viewer lists each accolade's icon and label under the card.

Counted accolades ("MVP ×3") are a later story.

## Endpoints

### `GET /cards/{card_id}/image`
Unchanged route; draws the new layout.

---

*This document is a stub created at feature planning time. Fill in implementation details once the feature is built.*
