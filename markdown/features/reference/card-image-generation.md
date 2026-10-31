# Card Image Generation

Each card in the deck is represented as a dynamically composited PNG served by `GET /cards/{card_id}/image`. The image is generated on demand by `backend/image.py` using the Pillow library.

This is the Card Art Accolade Redesign pipeline (`markdown/plans/plan-card-art-accolade-redesign.md`): new illustrated templates with purpose-built slots for photo, team logo, name, team name, stats and a 3×2 accolade badge grid. It replaces the original restored-art pipeline from [Card Visuals Rollback](card-visuals-rollback.md) (#228); see [Card Art Accolade Redesign](card-art-accolade-redesign.md) for what changed and why.

---

## Template files

Four rarity-specific PNG templates must be present under `assets/card_templates/`:

| Rarity | File |
|---|---|
| Common | `Card_Grey.png` |
| Rare | `Card_Blue.png` |
| Epic | `Card_Purple.png` |
| Legendary | `Card_Gold.png` |

All templates share the same canvas size: **687 × 1024 px**, RGBA.

**Holo:** a Holo Legendary (`cards.is_holo`) always uses `assets/card_templates/Card_Holo.png` — a dedicated illustrated template, not a procedurally generated effect. There is no fallback: if the file is missing, `_load_template` lets Pillow's `FileNotFoundError` propagate rather than silently substituting a generated sheen. The procedural sheen path (`_holo_sheen`, `warn_if_holo_template_missing`, `_HOLO_SHEEN_ALPHA`) was removed by the redesign.

**Accolades are drawn on the image again** (`_ACCOLADE_ICON_FILES`, `_composite_accolades`): up to 6 badge icons from `assets/accolades/` fill the template's 3×2 accolade grid, selected and priority-capped (see below). User tags are still not drawn: the card viewer lists them in its Tags section, same as since #228. See [Tag Symbols on Cards](tag-symbols-on-cards.md).

The assets directory is resolved at startup by searching several candidates (`assets/`, `Assets/`, `/app/Assets/`, etc.) for a folder containing `card_templates/Card_Grey.png`, `Card_Blue.png`, `Card_Purple.png` and `Card_Gold.png`. Linux containers use `/app/Assets` by convention; local development typically uses `assets/` or `Assets/` at the repo root.

The template PNG's slots are **opaque fills**, not transparent cutouts: the previous design (and the #228 restoration of it) had a transparent template composited *on top of* the photo/logo layers. The redesign flips this — the template is the base layer, and the photo, logo, text and accolade icons are pasted *on top of it* into their slots.

---

## Compositing pipeline

The image is built in six steps, in order:

1. **Template base** — the rarity (or Holo) template PNG is opened and used as the starting canvas. It already carries the frame, decorative chrome, and every slot's background fill.

2. **Player photo** — the player's OpenDota avatar image is downloaded and resized to exactly fill the photo slot (`_PHOTO_SLOT`), a square crop with no circular mask. If the avatar URL is unavailable or the download fails, the slot is left as the template's own fill (no placeholder for the photo).

3. **Team logo** — the team logo is loaded from the local Dotabuff PNG cache first (`assets/dotabuff_league_logos/<team-name>.png`), falling back to the HTTP `logo_url` stored on the team record, fetched only when `safe_logo_url` passes it (https on a `LOGO_HOST_ALLOWLIST` host, Steam's CDNs by default; see [Twitch Panel Abuse Limits](twitch-panel-abuse-limits.md)). It is **aspect-fit** into the logo box (`_LOGO_BOX`) — scaled to fit without cropping or distorting the source image, centred in the box, no padding trimmed from the source first. If neither source resolves, a solid black placeholder (`_blank_logo_placeholder`) sized to the box is pasted instead, so the slot is never left unpainted.

4. **Accolade badges** — up to 6 of the player's accolades are composited into the 3×2 accolade grid (`_ACCOLADE_COLS` × `_ACCOLADE_ROWS`), each badge icon aspect-fit into its cell. See "Accolade badges on the card" below.

5. **Name and team text** — the player name is drawn centred within the player name bar's own text area (`_NAME_BAR`); the team name within the team name bar's text area (`_TEAM_NAME_BAR`), which sits to the right of the bar's decorative icon and is **not** centred on the full card width (confirmed by mock-up review to read better than card-wide centring, even though the bar itself sits off the card's centreline).

6. **Stat modifiers** — modifier lines are drawn as a vertically centred block inside the stats box (`_STATS_BOX`).

---

## Layout coordinates

All positions are in pixels relative to the 687 × 1024 canvas, measured by pixel-scanning `assets/card_templates/Card_Grey.png`'s opaque slot fills. Every rarity (and Holo) shares the same layout — there is no per-rarity Y offset in this design.

| Slot | Constant | Rect (x0, y0, x1, y1) |
|---|---|---|
| Player photo (square) | `_PHOTO_SLOT` | `(222, 119, 473, 372)` |
| Player name bar's text area | `_NAME_BAR` | `(125, 416, 571, 469)` |
| Team name bar's text area | `_TEAM_NAME_BAR` | `(217, 499, 542, 545)` |
| Stats box | `_STATS_BOX` | `(93, 575, 601, 771)` |
| Team logo box | `_LOGO_BOX` | `(93, 815, 338, 937)` |

The accolade grid is 3 columns × 2 rows, ~58×59 px per cell:

| Constant | Value |
|---|---|
| `_ACCOLADE_COLS` | `(378, 460, 542)` — left edge of each column |
| `_ACCOLADE_ROWS` | `(804, 888)` — top edge of each row |
| `_ACCOLADE_CELL` | `(58, 59)` — (width, height) per cell |

Cells are numbered 0–5 in reading order (left to right, top to bottom); `_accolade_cell_rect(i)` returns a cell's rect.

If new template art is dropped in, re-measure these rects against the new files before trusting them — the redesign's own pixel-scan was a first-pass estimate, verified and adjusted against the shipped templates.

---

## Accolade badges on the card

`_ACCOLADE_ICON_FILES` maps each `accolades.ACCOLADE_KINDS` key to its badge filename under `assets/accolades/` — distinct from the Lucide icon name `ACCOLADE_KINDS` carries for use elsewhere on the site (the Players list, Teams tab, team popup, Hall of Fame, player popup). This map is local to `backend/image.py`; `ACCOLADE_KINDS` itself is untouched, since it is parity-tested against `frontend/app-globals.js`.

| `ACCOLADE_KINDS` key | Badge file |
|---|---|
| `div1` | `Accolade_Div1_Champion.png` |
| `div2` | `Accolade_Div2_Champion.png` |
| `div1_runner_up` | `Accolade_Div1_Runnerup.png` |
| `div2_runner_up` | `Accolade_Div2_Runnerup.png` |
| `div1_third` | `Accolade_Div1_Third.png` |
| `div2_third` | `Accolade_Div2_Third.png` |
| `most_points` | `Accolade_Most_Points.png` |
| `best_average` | `Accolade_Best_Average.png` |
| `best_match` | `Accolade_Best_Single_Match.png` |
| `fantasy_winner` | `Accolade_Season_Winner.png` |
| `played` | `Accolade_Played.png` |

`backend/routers/cards.py`'s `get_card_image` fetches the player's accolades the same way `GET /accolades` does (`accolades.accolades_for(db, [player_id])`), maps each one to its `ACCOLADE_KINDS` key (`accolades.kind_key`), and passes the resulting list as `generate_card_image`'s `accolade_keys` parameter — one list entry per accolade the player holds, so a kind won by multiple seasons (e.g. "played" for 7 seasons) appears once per season.

`image._select_accolade_keys(accolade_keys, limit=6)` first **deduplicates** to unique keys (first-seen order), then picks the 6 highest-priority ones with a **stable** sort on a card-face priority distinct from `accolades._KIND_ORDER` (which orders the detail list, not the card):

1. Division champion (`div1`, `div2`)
2. Division runner-up (`div1_runner_up`, `div2_runner_up`)
3. Division third place (`div1_third`, `div2_third`)
4. Fantasy winner (`fantasy_winner`)
5. Performance awards (`most_points`, `best_average`, `best_match`)
6. Seasons played (`played`)

Because the sort is stable and `accolades.accolades_for` already lists each player's accolades newest-season-first, this keeps each tier's entries in newest-first order without the card-face code needing to know about seasons itself. A kind earned in multiple seasons (e.g. "played" for 7 seasons, or `div1` champion twice) still takes only one grid slot.

**Count badge:** `image._accolade_counts(accolade_keys)` counts how many times each kind appears in the full (non-deduplicated) list. `_composite_accolades` draws a small badge — a filled circle with the number, or `"9+"` above 9 — over the bottom-right corner of a cell whose kind's count is 2 or more; a kind held once shows no badge.

A key with no entry in `_ACCOLADE_ICON_FILES` (e.g. stale data) or whose badge file is missing on disk is skipped — that grid cell stays blank rather than raising. A player with no accolades gets an empty grid (no placeholder icons). Since the image carries no server-side cache, a newly granted or changed accolade shows on the very next `GET /cards/{card_id}/image` request.

---

## Text rendering

Text is drawn centred within its own slot (`_draw_text_in_box`), not the full card width. All names are uppercased. A drop shadow is drawn 2 px offset before the main text to maintain legibility over varied template colours.

| Element | Font size | Fill colour |
|---|---|---|
| Player name | 34 pt | `(35, 35, 35)` dark |
| Team name | 24 pt | `(35, 35, 35)` dark |
| Modifier lines | 28 pt | `(200, 230, 210)` green-tint |

The name/team bar areas on the template are light-coloured, so dark text is used there. The stats box sits on a dark area of the template, so modifier text uses a light green tint.

The font fallback chain (tried in order):
1. `LiberationSans-Bold.ttf`
2. `FreeSansBold.ttf`
3. `DejaVuSans-Bold.ttf`
4. PIL built-in default (bitmap, low quality — indicates a missing font package)

---

## Stat modifier labels

Modifier lines are stacked as a vertically centred block inside the stats box (`_draw_stat_modifiers`). Each line shows the stat name and bonus percentage, e.g. `KILLS +10%`. Stat keys are mapped to human-readable labels from `scoring.STAT_LABELS` (shared with the Weekly Report points breakdown, issue #152), shown upper-case — see that module for the full label list. Lines are sorted alphabetically by stat key. If there are no modifiers (e.g. a Common card), the stats box is left empty.

---

## Team logo sources

The generator prefers locally cached Dotabuff logos over live HTTP fetches for reliability and speed:

1. **Local file** — `assets/dotabuff_league_logos/<team-name>.png` (downloaded during ingest; see `ingest.md`)
2. **HTTP fallback** — `team.logo_url` stored in the database (an OpenDota team logo URL on a Steam CDN), fetched only when `safe_logo_url` passes it (`LOGO_HOST_ALLOWLIST`, issue #171; see [Twitch Panel Abuse Limits](twitch-panel-abuse-limits.md)). A URL on any other host is never requested.

Both are aspect-fit into the logo box, plain aspect-fit of the source file as-is (no padding trimmed from the source first — a trimmed version was tried during design and reverted as looking worse). If neither source is available (e.g. pre-season, before a team's first match has been ingested and its logo scraped/set), `_blank_logo_placeholder()` supplies a solid black box of the same size instead, so the slot looks intentional rather than broken. Since the card image is generated fresh on every request with no server-side caching, the placeholder is automatically replaced by the real logo on the very next request once one becomes resolvable — no cache to invalidate. See [Card Team Logo Placeholder](card-team-logo-placeholder.md).

---

## API endpoint

### `GET /cards/{card_id}/image`

Returns the composited card PNG for any card regardless of ownership. Response headers: `Content-Type: image/png`, `Cache-Control: no-store, no-cache, must-revalidate`, `Pragma: no-cache`.

- Returns **404** if the card does not exist.
- Returns **503** if the Pillow library is not installed in the runtime environment.
- Returns **429** after 60 requests a minute from one IP (`RATE_LIMIT_CARD_IMAGE`), since every call renders a new image.

The image is generated fresh on every request (no server-side caching). The frontend adds a cache-bust query parameter after a reroll so the browser does not serve a stale image from its own cache.

---

## Adding or updating card templates

To change the card visual design, replace the rarity/Holo template PNGs under `assets/card_templates/`. The templates must:

- Be exactly **687 × 1024 px**, RGBA
- Carry their own opaque backgrounds for every slot (photo, name bar, team bar, stats box, logo box, 6 accolade cells) — the renderer pastes content *into* these slots, it does not cut holes through the template
- Keep the slot positions reasonably close to the coordinates in "Layout coordinates" above, or update the `_PHOTO_SLOT` / `_NAME_BAR` / `_TEAM_NAME_BAR` / `_STATS_BOX` / `_LOGO_BOX` / `_ACCOLADE_COLS` / `_ACCOLADE_ROWS` constants in `backend/image.py` to match (re-measure with a pixel scan — don't guess)

To change the accolade badge set, replace the files under `assets/accolades/` and update `_ACCOLADE_ICON_FILES` if any `ACCOLADE_KINDS` key's filename changes. Every `ACCOLADE_KINDS` key must have an entry.
