# Card Image Generation

Each card in the deck is represented as a dynamically composited PNG served by `GET /cards/{card_id}/image`. The image is generated on demand by `backend/image.py` using the Pillow library.

---

## Template files

Four rarity-specific PNG templates must be present in the assets directory:

| Rarity | File |
|---|---|
| Common | `Card_Template_Common.png` |
| Rare | `Card_Template_Rare.png` |
| Epic | `Card_Template_Epic.png` |
| Legendary | `Card_Template_Legendary.png` |

All templates share the same canvas size: **597 × 845 px**.

The template PNG is a fully-designed frame — rarity border, decorative elements, name plate, and background art — with transparent cutouts where the player avatar and team logo are composited underneath. The frame is layered on top of the player content so it always reads cleanly.

The assets directory is resolved at startup by searching several candidates (`assets/`, `Assets/`, `/app/Assets/`, etc.) for a folder containing all four template files. Linux containers use `/app/Assets` by convention; local development typically uses `assets/` or `Assets/` at the repo root.

---

## Compositing pipeline

The image is built in five layers, in order:

1. **Dark base** — a solid `(35, 37, 40)` RGBA fill at full card size. Provides the background colour for areas the template does not cover.

2. **Player avatar** — the player's OpenDota avatar image is downloaded, resized to a 350 × 350 px square (radius 175), circle-cropped with an alpha mask, and pasted onto the base centred at `(298, 375)`. If the avatar URL is unavailable or the download fails, the slot is left as the dark base colour.

3. **Team logo** — the team logo is loaded from the local Dotabuff PNG cache first (`assets/dotabuff_league_logos/<team-name>.png`), falling back to the HTTP `logo_url` stored on the team record. It is resized to 104 × 104 px (radius 52), circle-cropped, and pasted at `(444, 258)`. Missing logos are silently skipped.

4. **Template overlay** — the rarity template PNG is alpha-composited on top of the base, covering the avatar/logo layers with its frame. This is what provides the rarity border, name plates, and decorative chrome.

5. **Text and modifiers** — player name, team name, and stat modifier lines are drawn over the composite using `ImageDraw`.

---

## Layout coordinates

All positions are in pixels relative to the 597 × 845 canvas. Epic and Legendary templates have their content plates positioned slightly lower than Common and Rare; a `+8 px` Y offset (`_CARD_LAYOUT_Y_OFFSET_EPIC_LEGENDARY`) is applied to all dynamic content (avatar, team logo, text, modifiers) for those rarities so that text and images align with the template plates correctly.

| Element | Position |
|---|---|
| Player avatar centre | `(298, 375)` — radius 175 |
| Team logo centre | `(444, 258)` — radius 52 |
| Player name baseline Y | `90` (+ rarity offset) |
| Team name baseline Y | `155` (+ rarity offset) |
| First modifier line Y | `620` (+ rarity offset) |
| Modifier line spacing | `50 px` |

---

## Text rendering

Text is drawn centered horizontally on the card. All names are uppercased. A drop shadow is drawn 2 px offset before the main text to maintain legibility over varied template colours.

| Element | Font size | Fill colour | Max width before truncation |
|---|---|---|---|
| Player name | 32 pt | `(35, 35, 35)` dark | 480 px |
| Team name | 22 pt | `(35, 35, 35)` dark | — |
| Modifier lines | 30 pt | `(200, 230, 210)` green-tint | 500 px |

The name plate areas on the template are light-coloured, so dark text is used there. The modifier band sits below the portrait on a dark area of the template, so the modifier text uses a light green tint.

The font fallback chain (tried in order):
1. `LiberationSans-Bold.ttf`
2. `FreeSansBold.ttf`
3. `DejaVuSans-Bold.ttf`
4. PIL built-in default (bitmap, low quality — indicates a missing font package)

---

## Stat modifier labels

Modifier lines are rendered in the lower band of the card (below the portrait area). Each line shows the stat name and bonus percentage, e.g. `KILLS +10%`. Stat keys are mapped to human-readable labels:

| Stat key | Card label |
|---|---|
| `kills` | KILLS |
| `assists` | ASSISTS |
| `deaths` | DEATHS |
| `gold_per_min` | GPM |
| `obs_placed` | OBSERVER WARDS |
| `sen_placed` | SENTRY WARDS |
| `tower_damage` | TOWER DAMAGE |

Lines are sorted alphabetically by stat key and stacked from `y=620` downward. If there are no modifiers (e.g. a Common card), the lower band is left empty.

---

## Team logo sources

The generator prefers locally cached Dotabuff logos over live HTTP fetches for reliability and speed:

1. **Local file** — `assets/dotabuff_league_logos/<team-name>.png` (downloaded during ingest; see `ingest.md`)
2. **HTTP fallback** — `team.logo_url` stored in the database (Dotabuff CDN URL)

Both are circle-cropped before compositing. If neither source is available, the team logo slot is left empty.

---

## API endpoint

### `GET /cards/{card_id}/image`

Returns the composited card PNG for any card regardless of ownership. Response headers: `Content-Type: image/png`, `Cache-Control: no-cache`.

- Returns **404** if the card does not exist.
- Returns **503** if the Pillow library is not installed in the runtime environment.

The image is generated fresh on every request (no server-side caching). The frontend adds a cache-bust query parameter after a reroll so the browser does not serve a stale image from its own cache.

---

## Adding or updating card templates

To change the card visual design, replace the four template PNGs in the assets directory. The templates must:

- Be exactly **597 × 845 px**
- Use **RGBA** mode (transparency where player content should show through)
- Place the name plate area around **y ≈ 75–170** (where player name and team name are drawn)
- Leave the lower area around **y ≈ 620–750** clear for modifier text
- Position the portrait cutout centred near **(298, 375)**
- Position the team badge cutout centred near **(444, 258)**

If the plate positions shift significantly between rarities, adjust `_CARD_LAYOUT_Y_OFFSET_EPIC_LEGENDARY` in `backend/image.py` or introduce per-rarity offsets.
