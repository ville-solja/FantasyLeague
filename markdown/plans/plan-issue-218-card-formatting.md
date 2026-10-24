# Plan: Card Formatting

## Context
The card PNG (`backend/image.py`) was designed before accolades existed. Tag stickers (Caster, Season Winner) are pasted as 60 px discs in the top-left corner, on top of the frame ornament. They have no labels, and there is no room for a third or fourth accolade. Issue #218 asks for different card layouts, including radically different ones and ideas from trading card games, so the product owner can choose a direction.

A design canvas shows six portrait layouts and three landscape ones, each with a legendary card (3 modifiers, 3 accolades), a rare card (1 modifier, no accolades), and the legendary card at roster-slot size (180 px) and Twitch-panel size (110 px). It also has an accolade kit (disc, medal, stamp, chip, empty slot): https://claude.ai/artifact/7EZ3WKh3GrN63FipYATfG8 (private until shared).

| Layout | Idea | Accolades |
|---|---|---|
| A · Classic TCG | Name bar, portrait between two pillars, type line with the logo, cream rules box | Discs in the right pillar (rarity gems in the left); names under the modifiers |
| B · Centrepiece | Ringed round portrait on a sunburst, full-size logo at the top, name and modifier chips below | Medallions down the left edge |
| C · Sports card | Light border, square photo with a side column, angled name band holding the logo, three stat boxes | Foil stamps in the column beside the photo |
| D · Stat block | 1.5× portrait beside a full-size logo, modifiers as move rows with a big +10% | Three fixed slots at the bottom; empty slots show dashed |
| E · Medals | Arched portrait, rarity stars, corner ornaments, logo on the arch | Medals on ribbons hanging from the arch |
| F · Side rail | A rail as wide as the portrait leaves holds the logo, rarity gem, accolades and the rarity name | Square tiles with short labels stacked in the rail |
| G · Landscape panorama | Portrait and rarity band on the left; full-size logo, name, modifier rows on the right | Chips with icon and label |
| H · Landscape broadcast | Portrait and full-size logo over a stream-style lower-third bar with name and modifiers | Medallions in a row beside the portrait |
| I · Landscape ticket | A coloured stub with a perforated edge; round 1.5× portrait; logo; modifiers as scoreboard boxes | Discs stacked in the stub; names under the team |

Assumptions:
- **The layout is chosen first.** The product owner picks one layout, or a mix, on the canvas before `/develop`. This plan's steps stay valid for any of the six. The chosen layout is recorded under "Chosen layout" below.
- **The server still renders one PNG.** `GET /cards/{id}/image` stays the only card picture. It is used by the website, the Twitch panel and the reports. New template PNGs, one per rarity, are drawn from scratch for the chosen layout around fixed slots (below); Pillow pastes the avatar, logo, text and accolades into those slots. Every layout also has a card number (the card id) and a foil sheen on legendary cards.
- **Accolades are today's user tags.** The card shows the tags of the user linked to the card's player, as today (`tag_keys`). Each tag's icon is `assets/stickers/{key}.png`; the card draws it inside the layout's badge shape. The tag's label appears where the layout has room (A, C) and in the card viewer. Counted accolades such as "MVP ×3" are a later story.
- **Overflow.** A layout shows up to its own maximum (3 in A, D and E; 4 in B, C and F). When there are more, the last place shows "+N".
- **Small sizes.** The roster slot (180 × 255) and the Twitch panel (about 110 px wide) show the same PNG scaled down. The name and the rarity must stay readable at 180 px. Accolades may become icons only.
- **Landscape (G, H, I).** A landscape card is 845 × 597 instead of 597 × 845. Choosing one changes more than `image.py`: the roster slots (180 × 255), the reveal modal, the draw animation (#205), the Weekly Report and the Twitch panel all assume a portrait card and need their sizes and grids changed. A landscape layout as a second format (for example for one rarity or a special card) would need a per-card format and is a larger change.
- **Image sizes.**
  - Team logos: all cached Dotabuff logos (`assets/dotabuff_league_logos/`) are 250 × 150 (5:3), and most have an opaque white or coloured background. Today `_load_team_logo_for_card` resizes them to a 104 × 104 square and `_circle_crop` cuts a circle, which squashes the wordmark and clips its ends.
  - Every template has a logo slot of exactly 250 × 150, 150 × 90 or 100 × 60 (1×, 0.6× or 0.4×), so a cached logo fills it with no crop and is never enlarged.
  - A logo fetched from `logo_url` (the fallback; size unknown) is fitted inside the plate without stretching.
  - Player avatars: the Steam `avatarfull` from OpenDota is 184 × 184. Today's portrait circle is 350 px, about 1.9× enlarged.
  - Every template has a portrait slot of exactly 368 × 368 (2×) or 276 × 276 (1.5×), so the avatar fills it with no crop, no stretch and no filler. The frame is drawn around the slot. The canvas board "Image sizes" shows the slot sizes.
- **League-agnostic.** No league name or logo on the card.
- **Rank medal (#221).** Every template has a rank slot for the player's medal badge (medal shape and colour with stars, or "Immortal #N"), drawn by `_draw_rank_medal` from `players.rank_tier` and `leaderboard_rank`; the slot is left empty when the rank is null. See `plan-issue-221-player-rank-medals.md`.
- **Same data.** No change to cards, modifiers, rarities, tags or their endpoints.

Chosen layout: **A · Classic TCG** (product owner, 2026-10-24). On the 597 × 845 card (about 2× the canvas drawing, `LayoutA` on the canvas):
- **Frame:** rarity-coloured border with rounded corners; cross-hatch pattern in the rarity colour; foil sheen on legendary.
- **Name bar:** the player name, with the card number (`#` + card id) on the right.
- **Portrait row:** the portrait slot of 368 × 368 (2×), with a 6 px rarity-coloured border, between two pillars about 80 px wide.
  - The left pillar holds the rarity gems: 1 for common, 2 for rare, 3 for epic and 4 for legendary. Under them is the rank medal slot (#221).
  - The right pillar holds the accolade discs, at most 4. When there are more, the fourth place shows "+N".
- **Type line:** the team logo slot of 100 × 60 (0.4×), the team name, and the rarity name.
- **Rules box:** the cream box holds the modifier lines (up to 3), with the accolade names on a line at its foot.
- **Templates:** drawn from scratch by a generator script in the repo, so they can be rebuilt. The file names stay `Card_Template_<Rarity>.png`, so asset resolution doesn't change.

Resolves GitHub issue #218.

## User Stories

### Choose a New Card Layout
**User story**
As the product owner, I want to compare radically different card layouts so that I can choose one that fits accolades and still reads as a trading card.

**Acceptance criteria**
- A design canvas shows at least five different layouts, each with a legendary card (3 modifiers, 3 accolades) and a rare card (1 modifier, no accolades)
- Each layout is also shown at roster-slot size (180 px wide) and Twitch-panel size (110 px wide)
- The canvas shows the current card for comparison and the accolade badge styles
- The chosen layout is written into this plan before implementation starts

### Accolades Have Their Own Place on the Card
**User story**
As a player, I want a card's accolades to sit in a dedicated place on the card so that I can see what the player has achieved without the badges covering the frame.

**Acceptance criteria**
- Every tag of the player's linked user is drawn in the layout's accolade area, in the tag's own icon and colour, never on top of the name, portrait, team logo or frame
- The accolade area holds up to the layout's maximum; more accolades show "+N" in the last place
- A card with no accolades shows the layout's empty state (an empty accolade pillar) and no gap that looks broken
- A new tag with a sticker file appears on cards without a code change, as today
- A tag without a sticker file still shows, with a generic badge and its first letter

### Card Reads at Every Size
**User story**
As a player, I want a card to stay readable in my roster and in the Twitch panel so that the smaller views are as useful as the full card.

**Acceptance criteria**
- At 180 px wide, the player name, rarity and modifier values are readable
- At 110 px wide, the rarity and the portrait are clear; text may be too small to read
- Rarity is told by more than colour: a label, stars or a gem shape differs between rarities
- Team logos keep their 5:3 shape: never squashed into a square or cut into a circle that clips the wordmark
- The portrait and logo slots have the exact proportions of their sources (1:1 and 5:3) at a whole or simple scale (avatar 1.5× or 2×; logo 1×, 0.6× or 0.4×), so nothing is cropped, stretched or filled
- Common, rare, epic and legendary cards use the same layout, with 0 to 3 modifiers
- The player's rank medal (#221) is drawn in the template's rank slot, and left out when the player has no rank

### See Accolade Names in the Card Viewer
**User story**
As a player, I want to see the names of a card's accolades when I open the card so that I know what each badge means.

**Acceptance criteria**
- The card viewer (the reveal modal, opened from a draw, My Team, the Weekly Report or the own-player notice) lists the accolades under the card image: icon and label
- The list is empty, and takes no space, when the card has no accolades
- The labels come from the tag definitions (`TagDefinition.label`)

### Counted Accolades *(not yet implemented)*
**User story**
As a player, I want accolades such as match MVP picks to show how many times they were earned so that a standout player's card shows it.

**Acceptance criteria**
- An accolade can carry a count, shown as "×N" next to its icon (for example "MVP ×3")
- The count comes from stored data (for example Twitch MVP picks per player)
- Needs a decision on which counted accolades exist and where their data comes from

## Implementation

### Critical Files
| File | Change |
|---|---|
| `backend/image.py` | The chosen layout: positions, frame drawing or new templates, the accolade area with overflow, rarity marker |
| `assets/Card_Template_*.png` | Replaced or removed, depending on the chosen layout |
| `backend/routers/cards.py` | `GET /cards/{id}/image` passes tag keys and labels in the user's tag order; the card data the viewer uses gains the accolade list |
| `frontend/app-cards.js`, `frontend/index.html`, `frontend/style.css` | Accolade list under the card in the card viewer |
| `markdown/features/reference/card-image-generation.md` | New layout, coordinates and accolade area |
| `markdown/features/reference/card-formatting.md` | Feature doc |
| `markdown/stories/user-tags.md` | Sticker story points to the accolade area |
| `backend/tests/test_issue_218_card_formatting.py` | Layout and accolade tests |

### Step 1 — Choose the layout
- Done: layout A (see "Chosen layout" in the Context). The answers to the open points below are recorded there.
- Settle the open design points:
  - the slot scales (portrait 1.5× or 2×, logo 1×, 0.6× or 0.4×);
  - the accolade maximum;
  - the empty state;
  - the portrait size, given the 184 px avatars.

### Step 2 — Layout in `image.py`
- Replace the layout constants (`_BIG_CIRCLE`, `_SMALL_CIRCLE`, `_PLAYER_NAME_Y`, `_MODIFIERS_START_Y` and the rest) with the chosen layout's. Keep one layout table per rarity only where the frames differ.
- Draw the rarity marker (label, stars or gem) so rarity does not depend on colour alone.
- Keep the 597 × 845 canvas size for a portrait layout, so the frontend's aspect ratios and the draw animation (#205) stay valid. A landscape layout also changes the frontend card sizes (see Assumptions).

### Step 2b — Logo and avatar sizes
- Draw the new rarity templates (597 × 845, RGBA) for the chosen layout from scratch, with transparent cutouts at the exact slot rectangles. Record each slot rectangle in `image.py` (`_PORTRAIT_SLOT`, `_LOGO_SLOT`).
- Team logos: resize the 250 × 150 source to the logo slot (an exact scale). A fallback logo of another shape is fitted inside the slot (`ImageOps.contain`, centred) on the slot's plate colour. No circle crop. This also fixes today's squashed logos.
- Avatars: resize the 184 × 184 source to the portrait slot (276 or 368). A round or arched slot uses a mask of that shape.
- Never stretch a logo or avatar out of its aspect ratio.

### Step 3 — Accolade area
- Replace `_apply_stickers(img, tag_keys)` with `_draw_accolades(img, accolades, layout)`, where `accolades` is a list of `{key, label}`.
- Each accolade is drawn in its badge shape, with the sticker PNG as its icon. A missing sticker gets a generic badge with the label's first letter.
- Overflow: past the maximum, the last place shows "+N".
- Keep the path check (`is_relative_to(sticker_root)`) from today's `_apply_stickers`.

### Step 4 — Accolades in the card data and viewer
- The card image route resolves `{key, label}` pairs. The card lists the viewer reads (roster, reveal) gain an `accolades` array.
- The card viewer shows the list under the card image.
- No new endpoint.

### Step 5 — Docs and tests
- Update `card-image-generation.md` and the feature doc.
- Tests:
  - the renderer draws each rarity with 0 to 3 modifiers and 0, 1, 3 and 5 accolades without error, at 597 × 845;
  - overflow draws "+N";
  - a missing sticker falls back to the letter badge;
  - a sticker path outside the sticker folder is ignored;
  - a square or tall fallback logo fits inside the logo slot without stretching;
  - a 184 × 184 avatar fills the portrait slot exactly, and a 250 × 150 logo fills the logo slot exactly;
  - the viewer lists accolade labels;
  - no league name in the renderer.

## Verification
- `cd backend && python -m pytest tests/test_issue_218_card_formatting.py`
- Render one card of each rarity with and without accolades and compare with the canvas.
- Check the roster at 180 px and the Twitch panel at 110 px: name and rarity readable in the roster.
- Grant a tag with no sticker file: the letter badge shows.
- Grant five tags: "+N" shows.
- No migration, no env vars.
