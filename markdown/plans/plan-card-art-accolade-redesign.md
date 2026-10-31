# Plan: Card Art Accolade Redesign

## Context
Issue #228 restored the original illustrated card templates and moved accolades and tags off the card face entirely, because the layout A (#218) frame had no clean place to put them. New template artwork has since been produced that *does* have purpose-built slots for everything a card needs — player photo, team logo, player name, team name, stats, and a 3×2 accolade grid — so the mismatch that caused #228 no longer applies. This plan adapts the renderer (`backend/image.py`) to the new templates and accolade badge icons, which are already designed and sitting in the repo (untracked, unwired). Tags stay off the card face; only accolades return, using dedicated badge art instead of the Lucide icon pips used elsewhere on the site.

Card canvas size changes from 597×845 to 687×1024 (a different aspect ratio), the player photo becomes a square crop instead of a circle crop, and the team logo becomes a larger aspect-fit box instead of a small circle — all driven by the new template's slot shapes, not a stylistic choice.

## User Stories

### New Card Template With Accolade Slots
**User story**
As a player, I want my card's name, team name, photo, team logo and stats to sit inside the new illustrated template's dedicated slots so that the art and the accolades read as one design instead of overlapping symbols.

**Acceptance criteria**
- `GET /cards/{id}/image` renders on the new rarity templates (Common → Grey, Rare → Blue, Epic → Purple, Legendary → Gold) instead of the originals
- Player photo is composited as a square portrait filling the template's photo slot (no circular crop)
- Team logo is composited inside the template's dedicated logo box, scaled to fit without distortion (no circular crop)
- Player name and team name are drawn in their own template bars, each sized and positioned for that bar
- Stat modifier lines are drawn inside the template's stats box
- Card size changes to 687 × 1024; every view that shows a card image (My Team, collection, draw reveal, card viewer, Weekly Report) displays correctly at the new size
- Missing player photo or team logo leaves that slot visibly blank rather than broken (same placeholder intent as today, resized to the new slot shape)

### Accolades Printed on the Card Face
**User story**
As a player, I want my card's accolades shown as icons on the card itself so that a champion or top performer's card stands out without opening the player popup.

**Acceptance criteria**
- `GET /cards/{id}/image` composites up to 6 accolade icons into the template's accolade grid, one icon per accolade the player holds
- Each accolade kind uses its matching badge icon asset (e.g. Division 1 Champion → crown badge), not the Lucide icon used elsewhere on the site
- A player with no accolades shows an empty grid (no placeholder icons)
- A player with more than 6 accolades shows the 6 highest-priority ones: champion > runner-up > third place > fantasy winner > performance awards (Most Points, Best Average, Best Single Match) > seasons played, newest season first within a tier
- Accolades still show as detailed HTML pips/timeline elsewhere (Players list, Teams tab, team popup, Hall of Fame, player popup) — the card face icons are additive, not a replacement
- Accolade icons update on the very next card image request after an accolade is granted or changed, since the image has no server-side cache (same as the rest of the card)

### Dedicated Holo Template Art
**User story**
As a player, I want a Holo Legendary card to use its own illustrated holo template so that it looks distinct from a procedurally generated shine.

**Acceptance criteria**
- A Holo Legendary (`cards.is_holo`) uses the dedicated Holo template file for its base art
- The procedurally generated rainbow sheen effect is removed; no code path falls back to a generated shine
- All dynamic content (photo, logo, name, team, stats, accolades) composites onto the Holo template the same way as the rarity templates

## Implementation

### Critical Files
| File | Change |
|---|---|
| `assets/card_templates/Card_{Grey,Blue,Purple,Gold,Holo}.png` | New templates, moved from the untracked `assets/Card templates/` (dropping the space in the folder name) and git-tracked |
| `assets/accolades/Accolade_*.png` | New accolade badge icons, moved from the untracked `assets/Accolades/` and git-tracked |
| `assets/Card_Template_{Common,Rare,Epic,Legendary}.png`, `assets/Card_Template_Holo.png` (if present) | Removed — superseded by the new templates |
| `backend/image.py` | Rewritten: new `_CARD_SIZE`, new slot-rect constants (photo, team logo, name bar, team name bar, stats box, 6 accolade cells), compositing order flipped (template drawn first as base, then photo/logo/text/accolade icons pasted on top, since the new slots are opaque fills rather than transparent cutouts), square-crop helper for the photo, aspect-fit helper for the logo, accolade icon compositing with a priority/cap-at-6 selection, holo path points at the real Holo template and the procedural sheen helper is removed |
| `backend/routers/cards.py` | `get_card_image` fetches the player's accolade keys (via the existing accolades lookup used by `GET /accolades`) and passes them into `generate_card_image` |
| `backend/accolades.py` | No change to `ACCOLADE_KINDS` (it's parity-tested against `frontend/app-globals.js` by `test_issue_230`); the accolade-key → badge-filename map lives only in `backend/image.py` |
| `backend/tests/test_issue_228_card_visuals_rollback.py` | Rewritten per its own comment: replace the whole-file `IMAGE_PY_SHA256`/template-hash pins with assertions on the new slot constants and compositing behaviour |
| `backend/tests/test_issue_107_card_team_logo_placeholder.py` | Rewritten for the new aspect-fit logo box geometry (no longer a circle) |
| `backend/tests/test_issue_217_tag_symbols_on_cards.py` | Confirm still passing unchanged — tags remain off the card face; only accolades return |
| `backend/tests/test_issue_205_card_draw_animations.py` | Check and update any card pixel-size assumptions for the new 687×1024 canvas |
| `backend/tests/test_issue_230_accolades_and_rank_in_player_popup.py` | Confirm `ACCOLADE_KINDS` parity is untouched |
| `frontend/app-cards.js`, `frontend/style.css` | Check for hardcoded 597/845 sizing or aspect-ratio assumptions tied to the old card dimensions (card viewer, roster/bench slots, draw reveal, deck stack) and update to the new ratio |
| `markdown/features/reference/card-image-generation.md` | Rewritten for the new pipeline, slot coordinates, and compositing order |
| `markdown/features/reference/card-art-accolade-redesign.md` | New reference doc recording this change (see stub below) |
| `markdown/features/reference/card-visuals-rollback.md` | Forward-pointer note that accolades are back on the card face as of this change |
| `markdown/features/reference/card-team-logo-placeholder.md` | Updated for the new logo box shape and placeholder treatment |

No migration, no new env var.

### Step 1 — Track the new assets
`git mv` (or `git add` after a manual move) the new template and accolade folders into clean, tracked paths: `assets/Card templates/*.png` → `assets/card_templates/*.png`, `assets/Accolades/*.png` → `assets/accolades/*.png`. Remove the old `Card_Template_*.png` files once the new ones are wired up and verified.

### Step 2 — Rewrite `backend/image.py`
- Measure exact slot rects against the real template art (the plan's investigation produced first-pass pixel estimates from `Card_Grey.png` — verify against the actual files before committing to constants):
  - Photo: square, roughly x 222–473, y 119–372
  - Player name bar: roughly x 117–576, y 415–468
  - Team name bar: roughly x 217–539, y 499–544
  - Stats box: roughly x 93–600, y 574–770
  - Team logo box: roughly x 93–338, y 815–937
  - Accolade grid (3×2, 6 cells ≈58×59): cols x [377–435, 459–517, 542–600], rows y [804–863, 885–946]
- Flip the compositing order: paste the rarity/holo template first as the full-canvas base, then paste the square-cropped photo, the aspect-fit logo, draw the name/team text, draw the stats text, then paste up to 6 accolade icons — all on top, since these slots are opaque fills, not transparent cutouts like the old templates.
- Team logo: plain aspect-fit of the source file as-is (no padding trim) — confirmed by mock-up review to look better than trimming the cached logo to its visible content bounds first.
- Team name text: centered within its own bar's text area (to the right of the bar's decorative icon), not centered on the full card width — confirmed by mock-up review to look better than card-wide centering, despite the bar itself sitting off the card's centerline.
- Add `_ACCOLADE_ICON_FILES`, a local dict mapping each `ACCOLADE_KINDS` key to its badge filename (e.g. `"div1": "Accolade_Div1_Champion.png"`, `"fantasy_winner": "Accolade_Season_Winner.png"`), and a selection helper that sorts a player's accolade keys by priority (champion > runner-up > third > fantasy winner > performance awards > played) and caps the result at 6.
- Point `_CARD_TEMPLATES` at the new Grey/Blue/Purple/Gold files and `_HOLO_TEMPLATE` at the new Holo file; delete `_holo_sheen` and `warn_if_holo_template_missing` (or whatever remains of the procedural-sheen path) since a real Holo template now always ships.

### Step 3 — Plumb accolades into the render call
`generate_card_image` gains an `accolade_keys` parameter (list of `ACCOLADE_KINDS` keys the player holds). `backend/routers/cards.py`'s `get_card_image` fetches the player's accolade keys the same way `GET /accolades` does and passes them through.

### Step 4 — Tests
Rewrite the tests listed in Critical Files. In particular, `test_issue_228_card_visuals_rollback.py`'s whole-file hash check must become assertions on the new named constants (slot rects, template filenames) per the comment already in that file, and `test_issue_107`'s circle-geometry assertions become aspect-fit-box assertions.

### Step 5 — Docs
Update `card-image-generation.md` in place for the new pipeline; add the new `card-art-accolade-redesign.md` reference doc; leave forward-pointer notes in `card-visuals-rollback.md` and `card-formatting.md`; update `card-team-logo-placeholder.md` for the new box shape.

## Verification
- Render a sample card for each rarity (common/rare/epic/legendary), a holo legendary, and players with 0, 1, and 7+ accolades; confirm slot alignment visually and tune the pixel constants if the art doesn't line up exactly with the first-pass measurements.
- `cd backend && python -m pytest tests/ -n auto -q` passes in full, including the rewritten card-image and accolade tests.
- `cd backend && DEBUG=true python -c "import main"` succeeds.
- Open My Team, the collection, a draw reveal, and the card viewer in a browser at the new 687×1024 aspect ratio; confirm no cropping, stretching or layout breakage.
- A player with a missing photo and a player with no team logo still render cleanly (blank slot, no broken image).
