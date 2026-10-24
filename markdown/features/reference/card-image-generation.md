# Card Image Generation

Each card is a PNG composited on demand by `backend/image.py` (Pillow) and served by `GET /cards/{card_id}/image`. The layout is **A · Classic TCG** (issue #218; see [Card Formatting](card-formatting.md)).

---

## Template files

Four rarity templates sit in the assets directory, all **597 × 845 px RGBA**:

| Rarity | File |
|---|---|
| Common | `Card_Template_Common.png` |
| Rare | `Card_Template_Rare.png` |
| Epic | `Card_Template_Epic.png` |
| Legendary | `Card_Template_Legendary.png` |

They are drawn from scratch by `backend/scripts/make_card_templates.py`, which reads the slot rectangles and colours from `image.py`. To change the frame, edit the script or the constants and rebuild:

```
python backend/scripts/make_card_templates.py
```

A template holds the rounded frame in the rarity colour, the cross-hatch pattern, the name bar, both pillars, the portrait border, the type-line plate and the cream rules box. The portrait and logo slots are transparent cutouts. `test_card_template_generator_script_exists` checks that the committed PNGs match the script's output.

The assets directory is found at startup by looking for a folder with all four files (`assets/`, `Assets/`, `/app/Assets/` and so on).

---

## Slots

Boxes are `(left, top, right, bottom)` on the 597 × 845 canvas, with right and bottom exclusive (as PIL crop boxes).

| Constant | Box | Holds |
|---|---|---|
| `_NAME_BAR` | `(24, 24, 573, 92)` | Player name (left), card number `#<card id>` (right, rarity colour) |
| `_LEFT_PILLAR` | `(24, 104, 104, 484)` | Rarity gems (`_GEM_AREA`) and the rank medal (`_RANK_SLOT`) |
| `_GEM_AREA` | `(24, 112, 104, 316)` | 1 / 2 / 3 / 4 diamond gems for common / rare / epic / legendary |
| `_RANK_SLOT` | `(28, 324, 100, 480)` | Rank medal (#221); empty when the rank is null |
| `_PORTRAIT_FRAME` | `(108, 104, 488, 484)` | 6 px rarity border around the portrait |
| `_PORTRAIT_SLOT` | `(114, 110, 482, 478)` | Avatar, **368 × 368** (the 184 × 184 Steam avatar at 2×) |
| `_RIGHT_PILLAR` | `(492, 104, 572, 484)` | Up to 4 accolade discs |
| `_TYPE_LINE` | `(24, 496, 573, 560)` | Logo, team name, rarity name (rarity colour) |
| `_LOGO_SLOT` | `(26, 498, 126, 558)` | Team logo, **100 × 60** (the 250 × 150 cached logo at 0.4×) |
| `_RULES_BOX` | `(24, 572, 573, 821)` | Up to 3 modifier lines; accolade names at the foot |

---

## Compositing

1. **Base:** `(35, 37, 40)` fill. It shows through an empty portrait slot.
2. **Avatar:** downloaded and resized to the portrait slot. A square avatar scales exactly; a non-square one is centre-fitted (`ImageOps.fit`), never stretched. No avatar leaves the slot as the base colour.
3. **Team logo:** the cached `assets/dotabuff_league_logos/<team>.png` first, then `team.logo_url` when `safe_logo_url` allows its host (issue #171). A 5:3 logo is resized to exactly 100 × 60. Any other shape is fitted with `ImageOps.contain`, centred on the dark plate. No circle crop. With no logo, `_blank_logo_placeholder` fills the slot with black (issue #107).
4. **Template** on top.
5. **Text and badges:** name and card number, team and rarity name, modifier lines (`_draw_rules_box`), gems (`_draw_rarity_gems`), rank medal (`_draw_rank_medal`), accolades (`_draw_accolades`).
6. **Foil sheen** (legendary only): a soft diagonal light band over the whole card (`_apply_foil_sheen`).
7. The rounded card shape is applied to the alpha channel, so the corners are transparent.

No league name or logo is drawn.

---

## Text

All text uses the font chain `LiberationSans-Bold` → `FreeSansBold` → `DejaVuSans-Bold` → PIL default. Long text shrinks to a minimum size, then ends with "…".

| Element | Size | Colour |
|---|---|---|
| Player name | 40, down to 30 | `#f3ead8` |
| Card number | 24 | rarity colour |
| Team name | 26, down to 20 | `#d8d0c0` |
| Rarity name | 28 | rarity colour |
| Modifier lines | 34 | `#2a2620`, label left and `+N%` right, dotted rule below |
| Accolade names | 22 | `#4a4336` |

At the roster size (180 px wide, ×0.30) the name is 12 px, the modifier lines 10 px and the rarity 8.4 px. A card with no modifiers shows "No stat modifiers" in the rules box.

Modifier labels come from `scoring.STAT_LABELS` in upper case, sorted by stat key, at most 3 lines.

---

## Accolades

`_draw_accolades(img, accolades)` takes `[{key, label}, ...]` in the user's tag order. Each accolade is a 60 px disc in the right pillar, centred vertically as a group, with a ring in the tag's colour (`_ACCOLADE_COLORS`, a neutral grey for other tags). The icon is `assets/stickers/{key}.png`. The sticker path must resolve inside the sticker folder (`is_relative_to`); otherwise, or when the file is missing, the disc shows the label's first letter. With more than 4 accolades, the fourth disc shows "+N". The names are listed at the foot of the rules box.

## Rank medal

`_draw_rank_medal(img, tier, lb, slot)` draws the medal shape (the CSS shapes of `.rank-medal-icon`) in its `--medal-*` colour, the medal name, and the stars, or "#N" for an Immortal with a leaderboard place. It draws nothing and returns `False` when the tier is null.

---

## API endpoint

### `GET /cards/{card_id}/image`

Returns the PNG for any card, regardless of owner. Headers: `Content-Type: image/png`, `Cache-Control: no-store, no-cache, must-revalidate`, `Pragma: no-cache`. The route passes the card id, the modifiers, the player's `rank_tier` and `leaderboard_rank`, and the accolades of the user linked to the player (`_accolades_for_players` in `routers/cards.py`).

- **404** if the card does not exist.
- **503** if Pillow is not installed.
- **429** after 60 requests a minute from one IP (`RATE_LIMIT_CARD_IMAGE`).

The image is rendered on every request (no server cache), so a new logo, tag or rank shows on the next request. The frontend adds a cache-bust parameter after a reroll.
