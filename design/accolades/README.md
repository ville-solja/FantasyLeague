# Accolade reference images

Reference art for the card artist: every accolade as Kana Cards draws it today. In the app they are not image files. Each is a [Lucide](https://lucide.dev) 0.453.0 icon on a small square plate, defined by `ACCOLADE_KINDS` in `frontend/app-globals.js`, with colours from `frontend/colors_and_type.css` and plates from `.accolade-pip` in `frontend/style.css`.

- `accolades-sheet.png`: all of them on one page with names, icons and colours.
- `svg/<key>-pip.svg`, `png/<key>-pip.png`: the accolade as drawn in the app (512 px PNG, transparent corners).
- `svg/<key>-icon.svg`, `png/<key>-icon.png`: the icon alone in its colour (512 px, transparent).

| Accolade | Key | Lucide icon | Plate | Colour |
|---|---|---|---|---|
| Div 1 Champion | `div1` | crown | filled | `#f0a83a` |
| Div 2 Champion | `div2` | trophy | filled | `#b8b8c0` |
| Div 1 / Div 2 Runner-up | `div1_runner_up`, `div2_runner_up` | medal | outlined | `#e4e4e8` |
| Div 1 / Div 2 Third place | `div1_third`, `div2_third` | award | outlined | `#cd8f5e` |
| Most Points | `most_points` | flame | outlined | `#e85d1c` |
| Best Average | `best_average` | gauge | outlined | `#f59256` |
| Best Single Match | `best_match` | zap | outlined | `#ffc96a` |
| Fantasy Winner | `fantasy_winner` | medal | outlined | `#ffd8b8` |
| Played | `played` | calendar-check | muted | `#8f8f99` |

**Plates:**
- **Filled:** the accolade colour as background, with a `#0a0a0c` icon.
- **Outlined:** the `#1a1a20` card colour with a coloured 1.5 px border and icon.
- **Muted:** the same card colour with a `#33333d` border.

All plates have 4 px corners at the app's size, and icons use stroke width 2.25.

The Div 1 and Div 2 versions of Runner-up and Third place look identical, and Fantasy Winner shares the medal icon with Runner-up. Text, not the symbol, tells them apart in the app.

Rendered 2026-10-31 from the code as it stood then. If accolades change, the images need re-rendering.
