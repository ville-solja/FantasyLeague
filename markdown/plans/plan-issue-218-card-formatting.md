# Plan: Card Formatting

## Context
The card PNG (`backend/image.py`) still uses the original templates. These are an AI-art frame with a 350 px portrait circle and a 104 px team-logo circle. The cached 250 × 150 logos are squashed into that circle, and the 184 × 184 avatar is cut round and enlarged about 1.9×. Issue #218 asked for new card layouts, and the product owner chose **layout A · Classic TCG** from the design canvas: https://claude.ai/artifact/7EZ3WKh3GrN63FipYATfG8 (private until shared; see the "LayoutA" and "Image sizes" boards).

A first build of layout A drew accolades on the PNG. It was reverted (commit `88e2b19`) because main took the other direction in the meantime:
- **Accolades as HTML pips (#50, #53):** season accolades live in `season_accolades` (`backend/accolades.py`) and show as HTML pips down the card's right edge (`accoladePipsHtml`, `.card-pips`), with chips under the card in the card viewer (`#revealAccolades`).
- **Tags as HTML pips (#217):** tag symbols are HTML pips down the left edge (`tagPipsHtml`, `.card-tag-pips`). The image draws no tags, so a grant shows at once.
- **Holo legendaries (#105):** `_load_template(ct, is_holo)` uses `Card_Template_Holo.png` when it exists, or the Legendary template with a generated iridescent sheen.
- **Rank medal (#221):** shipped as HTML in the popup and card viewer. The plan for #221 left the medal on the PNG to #218.

This plan rebuilds layout A on that design. The PNG draws the frame (its edge colour is the rarity), the exact portrait and logo slots, the rank medal, and a light shine on legendaries (much stronger on Holo). Its two pillars are where main's HTML pips sit: tags on the left, accolades on the right. Nothing about accolades or tags is drawn into the image. Product-owner review (24 Oct, plan doc below) removed the card number, the rarity gems and word, and the medal stars.

Layout A on the 597 × 845 card. The size is unchanged, so the roster, the reveal and the #205 draw animation keep their sizes.
- **Frame:** a rarity-coloured border with rounded corners, and a cross-hatch in the rarity colour.
- **Name bar:** the player name only.
- **Portrait row:** a portrait slot of 368 × 368 (the avatar at exactly 2×) with a 6 px rarity-coloured border, between two pillars about 80 px wide.
  - **Left pillar:** the tag pips at the top (HTML overlay). At the bottom, drawn on the PNG: the rank medal (#221).
  - **Right pillar:** the accolade pips (HTML overlay). The PNG draws only the empty pillar.
- **Type line:** the team-logo slot of 100 × 60 (the cached 250 × 150 logo at exactly 0.4×; no circle crop) and the team name. Rarity is told by the frame edge colour (common grey, rare blue, epic purple, legendary gold); the card viewer keeps the rarity word in text ("Legendary · Holo").
- **Rules box:** the cream box with up to 3 modifier lines, or "No stat modifiers".

Assumptions:
- **Reuse the reverted build.** Commit `46cb136` holds a working layout-A renderer and `backend/scripts/make_card_templates.py`. Start from them and remove the accolade drawing (`_draw_accolades`, the accolade names line, the `accolades` card data). Keep the slot constants, gems, rank medal, card number, logo fit and avatar 2×.
- **Holo and shine.** An ordinary legendary gets a light diagonal shine. Holo is drastically shinier: the generator writes `Card_Template_Holo.png` with a strong rainbow over the frame and pillars and only a faint tint on the text panels; the medal keeps a dark plate so it stays readable. Main's `_load_template` and the generated-sheen fallback stay.
- **Pips follow the pillars.** Today the pips are sized in px (`font-size: 11px`, `top: 3.4em`), so their place on the card drifts with the card's size. They become proportional to the card (container query units on the card wrapper), so they sit inside the pillars at roster size (180 px), in the reveal and in the Weekly Report. The pip markup and helpers don't change.
- **Twitch panel.** The panel shows the PNG, which gains the medal. It has no pips today, so its pillars stay empty there. Pips in the panel would be a separate issue.
- **Small sizes.** At 180 px wide the name and modifier values must stay readable. At 110 px, the portrait, edge colour and medal must stay clear.

Plan review doc with renders and the decisions to confirm: https://claude.ai/artifact/CKdDktuuHHNuGJ8C72pdpU. `/develop` follows its "Decisions to confirm" table.

Resolves GitHub issue #218.

## User Stories

### Choose a New Card Layout
**User story**
As the product owner, I want to compare radically different card layouts so that I can choose one that fits the card's symbols and still reads as a trading card.

**Acceptance criteria**
- A design canvas shows portrait and landscape layouts at full, roster (180 px) and Twitch-panel (110 px) sizes, with the current card for comparison
- The chosen layout (A · Classic TCG) is recorded in this plan

### Card Frame With Exact Portrait and Logo Slots
**User story**
As a player, I want the portrait and team logo on my card to look sharp and undistorted so that the card looks finished.

**Acceptance criteria**
- The card PNG is 597 × 845 and uses layout A for every rarity, with 0 to 3 modifiers
- The 184 × 184 avatar fills a 368 × 368 slot exactly (2×), with no crop, stretch or filler
- A 250 × 150 cached logo fills a 100 × 60 slot exactly (0.4×); a fallback logo of another shape is fitted inside the slot without stretching; no circle crop
- Rarity is shown by the frame edge colour only: common grey, rare blue, epic purple, legendary gold; no gems, rarity word or card number on the image
- The card viewer still names the rarity in text, so the edge colour is not the only signal
- An ordinary legendary has a light shine; a Holo legendary has a much stronger rainbow shine on the frame and pillars, with the text panels and medal still readable
- The templates are drawn by `backend/scripts/make_card_templates.py`, and the committed PNGs match its output
- No league name and no image from a Dota CDN on the card

### Rank Medal on the Card
**User story**
As a player, I want to see the player's rank medal on the card itself so that it shows wherever the card image is used, including the Twitch panel.

**Acceptance criteria**
- `GET /cards/{id}/image` draws the player's medal (#221) at the bottom of the left pillar: our own drawing of that Dota 2 medal in its primary colour (Herald bronze, Guardian green, Crusader teal, Archon yellow-green, Legend red, Ancient purple, Divine blue, Immortal gold) with the medal name; no stars, no leaderboard place
- The website badge (popup, card viewer) switches to the same emblems and colours and drops its stars and place
- An unranked player's card leaves the medal place empty, with no placeholder
- The medal uses the same medal colours as the website badge

### Pips Sit in the Pillars
**User story**
As a player, I want the tag and accolade symbols to sit neatly in the card's side pillars so that they never cover the portrait, the name or the frame.

**Acceptance criteria**
- Tag pips (#217) stack from the top of the left pillar and accolade pips (#50) from the top of the right pillar, on the roster card (180 px), the card viewer and draw reveal, and the Weekly Report cards
- The pips scale with the card, so they stay inside the pillars at every card size
- The tag pips end above the rank medal; with more pips than fit, the column stops there (no overlap with the medal or the type line)
- The pips keep their tooltips, keyboard focus and `aria-label`s; the PNG itself draws no tags or accolades

### Counted Accolades *(not yet implemented)*
**User story**
As a player, I want accolades such as match MVP picks to show how many times they were earned so that a standout player's card shows it.

**Acceptance criteria**
- An accolade pip can carry a count (the existing `accolade-pip-count`) for a counted kind such as Twitch MVP picks
- Needs a decision on which counted accolades exist and where their data comes from

## Implementation

### Critical Files
| File | Change |
|---|---|
| `backend/scripts/make_card_templates.py` | New (from commit `46cb136`, minus accolade discs): draws the four rarity templates and optionally `Card_Template_Holo.png`, with transparent portrait and logo cutouts |
| `assets/Card_Template_*.png` | Regenerated by the script |
| `backend/image.py` | Layout A: slot constants, portrait at 2×, logo fit into 100 × 60, medal emblems (`_draw_rank_medal`), rules box, light legendary shine; keeps `_load_template` and the Holo path; draws no accolades, tags, gems or card number |
| `backend/routers/cards.py` | The image route passes `card_id`, `rank_tier` and `leaderboard_rank` to `generate_card_image` |
| `frontend/app-globals.js`, `frontend/colors_and_type.css` (+ `design/` copy) | Medal badge: the same emblems and colours as the PNG, no stars or place (#221 follow-up) |
| `frontend/style.css` | `.card-pips` and `.card-tag-pips` positioned and sized in container units over the right and left pillars; the card wrappers (`.card-slot`, the reveal image wrap, Weekly Report cards) get `container-type: inline-size` |
| `markdown/features/reference/card-image-generation.md`, `card-formatting.md`, `player-rank-medals.md`, `tag-symbols-on-cards.md`, `season-winners-and-holo-cards.md` | Docs |
| `backend/tests/test_issue_218_card_formatting.py` | Tests (rebuilt from the reverted file) |

### Step 1 — Templates and renderer
- Restore `make_card_templates.py` and layout A in `image.py` from commit `46cb136`.
- Remove what main replaced:
  - the accolade discs and "+N" (`_draw_accolades`, `_load_sticker`);
  - the accolade names line in the rules box;
  - the `accolades` parameter.
- Keep main's `_load_template(ct, is_holo)`, `_holo_sheen` and `warn_if_holo_template_missing`. The generator also writes `Card_Template_Holo.png` (strong rainbow, faint on the text panels, medal on a dark plate). Ordinary legendaries keep a light shine.
- Remove the rarity gems, the rarity word and the card number. The left pillar's lower part holds the rank medal; its upper part is left plain for the tag pips.
- The right pillar is plain.

### Step 2 — Image route
- `get_card_image_route` reads `p.rank_tier` (already selected by #221's card queries) and passes it on.
- Nothing else in the card data changes; accolades and tags stay on `GET /accolades`.

### Step 3 — Pips over the pillars
- Give each card wrapper `container-type: inline-size`.
- Position the two pip columns in `cqw`:
  - left and right offsets at the pillar centres;
  - `top` at the portrait row;
  - pip size about 10 cqw (60 px on the 597 px card);
  - gap and max-height to the pillar's bottom (tags: above the medal).
- Keep a px fallback for browsers without container queries.
- Check the roster slot, the reveal, the draw animation's landing clone (#205) and the Weekly Report.

### Step 4 — Docs and tests
- Docs:
  - layout, slots and generator in `card-image-generation.md`;
  - `card-formatting.md` built parts;
  - `player-rank-medals.md`: the PNG medal is built;
  - the pips' new position in `tag-symbols-on-cards.md` and `season-winners-and-holo-cards.md`.
- Tests:
  - every rarity with 0 to 3 modifiers renders at 597 × 845;
  - the avatar and the 250 × 150 logo fill their slots exactly, and a square or tall fallback logo fits without stretching;
  - templates have transparent cutouts and match the generator;
  - the edge colour by rarity; no gems, rarity word or card number on the image; each of the eight medals draws in its colour without stars;
  - the medal is drawn for a ranked player and absent for an unranked one;
  - Holo renders with and without `Card_Template_Holo.png`, is much shinier than an ordinary legendary, and an ordinary legendary has a light shine;
  - `generate_card_image` takes no accolades or tags (#217 stays true);
  - the pip CSS uses container units and the wrappers declare `container-type`;
  - no league name in the renderer.
- Existing #50, #53, #105, #107, #217 and #221 tests stay green.

## Verification
- `cd backend && python -m pytest tests/test_issue_218_card_formatting.py tests/test_issue_50_season_winners_and_holo_cards.py tests/test_issue_217_tag_symbols_on_cards.py tests/test_issue_221_player_rank_medals.py`, then the full suite.
- Render one card per rarity, one Holo, one with a medal and one without, and compare with the canvas.
- In a browser, check a card with tag pips and accolade pips at 180 px, in the card viewer and in the Weekly Report: the pips sit inside the pillars.
- Check the Twitch panel at 110 px.
- No migration, no env vars.
