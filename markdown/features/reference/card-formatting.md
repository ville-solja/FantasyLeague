# Card Formatting

> **Rolled back by #228.** Layout A is no longer in use: the original illustrated templates and the pre-#218 renderer are back, `make_card_templates.py` and `Card_Template_Holo.png` are removed, and the accolade and tag pips left the card face for the card viewer. This page is kept as the record of the #218 design; see [Card Visuals Rollback](card-visuals-rollback.md) and `markdown/plans/plan-issue-228-card-visuals-rollback.md`. The design canvas below stays available if a new card design is tried later.

Card layout A · Classic TCG for the card PNG (issue #218). It has exact portrait and team-logo slots and shows the rarity by the frame's edge colour. Its two side pillars are where the HTML tag and accolade pips sit. Plan: `markdown/plans/plan-issue-218-card-formatting.md`. Design canvas: https://claude.ai/artifact/7EZ3WKh3GrN63FipYATfG8.

---

## Layout

*(built, rolled back by #228)* The 597 × 845 PNG is drawn from rarity templates made by `backend/scripts/make_card_templates.py`. It has:
- a name bar with the player name only;
- a 368 × 368 portrait (the 184 × 184 avatar at exactly 2×) between two pillars;
- a type line with a 100 × 60 team logo (the cached 250 × 150 logo at exactly 0.4×; another shape is fitted without stretching; no circle crop) and the team name;
- a cream rules box with up to 3 modifier lines, or "No stat modifiers".

*(built, rolled back by #228)* Rarity is shown by the frame edge colour only: common grey, rare blue, epic purple, legendary gold. The image has no rarity gems, rarity word or card number; the card viewer names the rarity in text ("Legendary · Holo").

*(built, rolled back by #228)* An ordinary legendary gets a light diagonal shine. A Holo legendary is much shinier: `Card_Template_Holo.png`, also written by the generator, has a strong rainbow over the frame and pillars and only a faint tint over the name bar, type line and rules box. Without that file, main's fallback stays: the Legendary template with the generated sheen. See [Card Image Generation](card-image-generation.md).

## Pillars

*(built, rolled back by #228)*
- **Left pillar:** the tag pips (#217, HTML overlay). The PNG draws only the empty pillar.
- **Right pillar:** the accolade pips (#50, HTML overlay). The PNG draws only the empty pillar.

The pips are sized and placed in container query units (`cqw`) on the card wrappers (`.card-slot`, `.reveal-img-wrap`, `.draw-landing`), with a px fallback, so they stay centred in the pillars at roster size and in the card viewer. Each column starts at the portrait row and stops at the pillar's bottom. The Weekly Report shows avatar thumbnails and opens a card in the card viewer, where the pips sit the same way. The Twitch panel draws its own card art (`twitch-extension/panel.js` loads no card PNG), so the layout and the pips don't reach it. See [Tag Symbols on Cards](tag-symbols-on-cards.md).

## Rank medal

*Deferred (product-owner decision, 25 Oct).* The PNG draws no medal, `generate_card_image` takes no rank arguments, and the website badge (#221) stays as it is. See [Player Rank Medals](player-rank-medals.md).

## Endpoints

### `GET /cards/{card_id}/image`
Unchanged route and arguments. It drew layout A until #228; it now draws the original art again.

---

*Layout A was built (#218) and rolled back by #228; this page is kept as the record of that design.*
