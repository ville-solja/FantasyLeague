# Card Formatting

Card layout A · Classic TCG for the card PNG (issue #218). It has exact portrait and team-logo slots, rarity by frame edge colour and the rank medal. Its two side pillars are where the HTML tag and accolade pips sit. Plan: `markdown/plans/plan-issue-218-card-formatting.md`. Design canvas: https://claude.ai/artifact/7EZ3WKh3GrN63FipYATfG8.

---

## Layout

*(planned)* The 597 × 845 PNG is drawn from new rarity templates made by `backend/scripts/make_card_templates.py`. It has:
- a name bar with the player name;
- a 368 × 368 portrait (the 184 × 184 avatar at exactly 2×) between two pillars;
- a type line with a 100 × 60 team logo (the cached 250 × 150 logo at exactly 0.4×, no circle crop) and the team name;
- a cream rules box with up to 3 modifier lines.

Rarity is shown by the frame edge colour (grey, blue, purple, gold); the card viewer names it in text. Legendaries get a light shine and Holo a much stronger one. Holo legendaries keep main's `_load_template` path: `Card_Template_Holo.png`, or the generated sheen over the Legendary frame. See [Card Image Generation](card-image-generation.md).

## Pillars

*(planned)*
- **Left pillar:** the tag pips (#217, HTML) at the top; at the bottom, drawn on the PNG, the rank medal (#221).
- **Right pillar:** the accolade pips (#50, HTML).

The pips are sized in container units, so they stay inside the pillars at roster size, in the card viewer and in the Weekly Report. The PNG draws no tags or accolades.

## Endpoints

### `GET /cards/{card_id}/image`
Unchanged route. *(planned)* It draws layout A with the rank medal (Dota 2 medal emblems in their primary colours, no stars).

---

*This document is a stub created at feature planning time. Fill in implementation details once the feature is built.*
