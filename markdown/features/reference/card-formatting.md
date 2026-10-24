# Card Formatting

The card layout that gives accolades (user tags such as Caster and Season Winner) their own place on the card PNG, with labels in the card viewer (issue #218). Plan: `markdown/plans/plan-issue-218-card-formatting.md`. Design canvas with the layout options and an accolade kit: https://claude.ai/artifact/7EZ3WKh3GrN63FipYATfG8.

---

## Layout

Layout **A · Classic TCG**, on the same 597 × 845 canvas as before, so the roster, the reveal modal and the draw animation (#205) keep their sizes:

- name bar with the player name and the card number (`#<card id>`);
- a 368 × 368 portrait (the avatar at exactly 2×) between two pillars: rarity gems and the rank medal (#221) on the left, accolade discs on the right;
- type line with a 100 × 60 team logo (the cached logo at exactly 0.4×; no circle crop), the team name and the rarity name;
- cream rules box with up to 3 modifier lines and the accolade names at its foot;
- cross-hatch in the rarity colour, and a foil sheen on legendary cards.

Rarity is shown by colour, by the number of gems (1 to 4) and by its name. The templates are drawn by `backend/scripts/make_card_templates.py`. Slots, sizes and fonts: [Card Image Generation](card-image-generation.md).

## Accolades

The tags of the user linked to the card's player, in the order they were granted, as `{key, label}`. On the PNG each is a disc in the right pillar with `assets/stickers/{key}.png` as its icon, or the label's first letter when there is no sticker. Up to 4 discs; with more, the fourth shows "+N". A card with no accolades has an empty pillar.

The card viewer (reveal modal) lists each accolade under the card image as an icon and a label (`#revealAccolades`). The icon is `/assets/stickers/{key}.png`, replaced by a letter chip when the file does not load. The list is hidden when empty.

*(planned)* Counted accolades ("MVP ×3") are a later story.

## Endpoints

### `GET /cards/{card_id}/image`
Draws layout A, with the accolades, card number and rank medal.

### Card data (`routers/cards.py`)
Each card in `GET /roster/{user_id}`, the `POST /draw` and `POST /draw/booster/{team_id}` responses, and `GET /cards/{card_id}`, and each roster card of the Weekly Report, has an `accolades` array of `{key, label}` (empty when the player has no linked user or no tags).

---

*This document is a stub created at feature planning time. Fill in implementation details once the feature is built.*
