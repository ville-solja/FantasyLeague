# Card Image Generation

Each card is a PNG composited on demand by `backend/image.py` (Pillow) and served by `GET /cards/{card_id}/image`. The layout is **A · Classic TCG** (issue #218; see [Card Formatting](card-formatting.md)).

---

## Template files

Four rarity templates, and the Holo template, sit in the assets directory, all **597 × 845 px RGBA**:

| Card | File |
|---|---|
| Common | `Card_Template_Common.png` |
| Rare | `Card_Template_Rare.png` |
| Epic | `Card_Template_Epic.png` |
| Legendary | `Card_Template_Legendary.png` |
| Holo Legendary (issue #53) | `Card_Template_Holo.png` (optional) |

They are drawn from scratch by `backend/scripts/make_card_templates.py`, which reads the slot rectangles and colours from `image.py`. To change the frame, edit the script or the constants and rebuild all five files:

```
python backend/scripts/make_card_templates.py
```

A rarity template holds the rounded frame in the rarity colour, the cross-hatch pattern, the name bar, both pillars, the portrait border, the type-line plate and the cream rules box. The portrait and logo slots are transparent cutouts. The Holo template is the Legendary one under a strong diagonal rainbow on the frame body, pillars and portrait border, a faint tint on the name bar, type line and rules box (so the text stays readable) and a light one on the outer edge (so it still reads gold). `test_issue_218_card_formatting.py` checks that the committed PNGs match the script's output.

**Holo fallback:** `_load_template(ct, is_holo)` uses `Card_Template_Holo.png` when it exists. It is not part of the four-template check. Without it, the Legendary template gets a generated iridescent sheen (`_holo_sheen`: a rainbow at low opacity, masked by the template's alpha so the cutouts stay untouched), and the missing file is logged once per process, at startup (`warn_if_holo_template_missing`) or on the first Holo render.

**Accolades and user tags are not drawn on the image.** The player's accolade pips and tag pips are HTML overlays in the frontend, over the right and left pillars, so they stay hoverable and update without rebuilding images ([Tag Symbols on Cards](tag-symbols-on-cards.md), [Season Winners and Holo Cards](season-winners-and-holo-cards.md)). `generate_card_image` takes no tags, accolades, card id or rank.

The assets directory is found at startup by looking for a folder with all four rarity files (`assets/`, `Assets/`, `/app/Assets/` and so on).

---

## Slots

Boxes are `(left, top, right, bottom)` on the 597 × 845 canvas, with right and bottom exclusive (as PIL crop boxes).

| Constant | Box | Holds |
|---|---|---|
| `_NAME_BAR` | `(24, 24, 573, 92)` | Player name (left) |
| `_LEFT_PILLAR` | `(24, 104, 104, 484)` | Empty in the PNG; the tag pips sit over it (HTML) |
| `_PORTRAIT_FRAME` | `(108, 104, 488, 484)` | 6 px rarity border around the portrait |
| `_PORTRAIT_SLOT` | `(114, 110, 482, 478)` | Avatar, **368 × 368** (the 184 × 184 Steam avatar at 2×) |
| `_RIGHT_PILLAR` | `(492, 104, 572, 484)` | Empty in the PNG; the accolade pips sit over it (HTML) |
| `_TYPE_LINE` | `(24, 496, 573, 560)` | Logo and team name |
| `_LOGO_SLOT` | `(26, 498, 126, 558)` | Team logo, **100 × 60** (the 250 × 150 cached logo at 0.4×) |
| `_RULES_BOX` | `(24, 572, 573, 821)` | Up to 3 modifier lines |

The rarity is shown by the frame's edge colour only (`_RARITY_COLORS`, the same values as the `--k-rarity-*` tokens): common grey, rare blue, epic purple, legendary gold. The image has no rarity gems, rarity word, card number or rank medal; the card viewer names the rarity in text ("Legendary · Holo").

---

## Compositing

1. **Base:** `(35, 37, 40)` fill. It shows through an empty portrait slot.
2. **Avatar:** downloaded and resized to the portrait slot. A square avatar scales exactly; a non-square one is centre-fitted (`ImageOps.fit`), never stretched. No avatar leaves the slot as the base colour.
3. **Team logo:** the cached `assets/dotabuff_league_logos/<team>.png` first, then `team.logo_url` when `safe_logo_url` allows its host (https on a `LOGO_HOST_ALLOWLIST` host, issue #171; see [Twitch Panel Abuse Limits](twitch-panel-abuse-limits.md)). A 5:3 logo is resized to exactly 100 × 60. Any other shape is fitted with `ImageOps.contain`, centred on the dark plate. No circle crop. With no logo, `_blank_logo_placeholder` fills the slot with black (issue #107).
4. **Template** on top (`_load_template`, Holo as above). An unknown rarity uses the common template.
5. **Text:** player name, team name, modifier lines (`_draw_rules_box`).
6. **Shine:** an ordinary legendary gets a light diagonal light band over the whole card (`_apply_foil_sheen`). A Holo legendary gets its shine from its template (or the generated sheen) instead.
7. The rounded card shape is applied to the alpha channel, so the corners are transparent.

No league name or logo is drawn, and no image from a Dota CDN.

---

## Text

All text uses the font chain `LiberationSans-Bold` → `FreeSansBold` → `DejaVuSans-Bold` → PIL default. Long text shrinks to a minimum size, then ends with "…".

| Element | Size | Colour |
|---|---|---|
| Player name | 40, down to 30 | `#f3ead8` |
| Team name | 28, down to 20 | `#d8d0c0` |
| Modifier lines | 34 | `#2a2620`, label left and `+N%` right, dotted rule below |

At the roster size (180 px wide, ×0.30) the name is 12 px and the modifier lines 10 px. A card with no modifiers shows "No stat modifiers" in the rules box.

---

## Stat modifier labels

Modifier lines are drawn in the rules box. Each line shows the stat name and bonus percentage, e.g. `KILLS +10%`. Stat keys are mapped to human-readable labels from `scoring.STAT_LABELS` (shared with the Weekly Report points breakdown, issue #152), shown upper-case:

| Stat key | Card label |
|---|---|
| `kills` | KILLS |
| `assists` | ASSISTS |
| `deaths` | DEATHS |
| `gold_per_min` | GPM |
| `obs_placed` | OBSERVER WARDS |
| `last_hits` | LAST HITS |
| `denies` | DENIES |
| `towers_killed` | TOWERS |
| `roshan_kills` | ROSHAN |
| `teamfight_participation` | TEAMFIGHT |
| `camps_stacked` | CAMPS STACKED |
| `rune_pickups` | RUNES |
| `firstblood_claimed` | FIRST BLOOD |
| `stuns` | STUNS |

Lines are sorted by stat key, at most 3, from `y=606` down in steps of 58 px.

---

## Team logo sources

1. **Local file:** `assets/dotabuff_league_logos/<team-name>.png`, 250 × 150, downloaded during ingest (see `ingest.md`).
2. **HTTP fallback:** `team.logo_url` (an OpenDota team logo on a Steam CDN), fetched only when `safe_logo_url` passes it. A URL on any other host is never requested.

Neither is circle-cropped. With neither, `_blank_logo_placeholder()` fills the slot with black. The image is generated on every request, so the real logo replaces the placeholder as soon as one resolves.

---

## API endpoint

### `GET /cards/{card_id}/image`

Returns the composited card PNG for any card regardless of ownership. Response headers: `Content-Type: image/png`, `Cache-Control: no-store, no-cache, must-revalidate`, `Pragma: no-cache`.

- Returns **404** if the card does not exist.
- Returns **503** if the Pillow library is not installed in the runtime environment.
- Returns **429** after 60 requests a minute from one IP (`RATE_LIMIT_CARD_IMAGE`), since every call renders a new image.

The image is generated fresh on every request (no server-side caching). The frontend adds a cache-bust query parameter after a reroll so the browser does not serve a stale image from its own cache.

---

## Changing the templates

Edit `backend/scripts/make_card_templates.py` (or the slot and colour constants in `image.py`) and rerun it; never edit the PNGs by hand. Keep the portrait slot at 368 × 368 and the logo slot at 100 × 60 so the avatar and logo scale exactly. If the pillars move, move the pip overlay in `frontend/style.css` too (the `--card-u` rules, see [Tag Symbols on Cards](tag-symbols-on-cards.md)).
