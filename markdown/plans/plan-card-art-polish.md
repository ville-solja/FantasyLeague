# Plan: Card Art Polish

## Context
Five refinements surfaced from live testing of the card-art-accolade-redesign (the new illustrated templates with dedicated photo/logo/name/team/stats/accolade slots, shipped in #239): the accolade count badge is hard to read, the accolade badges give no information on hover, the card face has no click-through to a player's or team's profile, team logos fill their slot inconsistently, and the My Team roster/bench cards are small with an unnecessary horizontal scrollbar. None of these are regressions in the base redesign — they're follow-up polish once the new templates were seen with real data. No GitHub issue backs this; it is a direct description of five testing findings.

The team-logo inconsistency (item 4) was investigated and confirmed empirically before this plan was written: `_aspect_fit` in `backend/image.py` is mathematically correct "contain" behaviour, not a stretch bug, but it lets a team logo's own aspect ratio decide whether the gap lands on the sides or top/bottom of the box — inconsistent across teams, read by the user as "stretching". The fix is a fit-mode change (contain → cover for this one slot), not a correctness fix.

## User Stories

### Legible, Informative Accolade Badges
**User story**
As a player, I want the accolade count numbers on my card to be easy to read and each badge to explain itself on hover, so that I can tell what I've earned without leaving the card view.

**Acceptance criteria**
- The accolade count badge's digits are at least 20% larger than before, and the badge circle grows enough that a "9+" count never clips its edge
- Hovering, focusing or tapping any accolade badge on a rendered card shows a tooltip naming that accolade and, when held more than once, how many times and in which seasons
- The tooltip's accolade order and count match exactly what's painted on the card face (same selection, priority and dedup rule as the backend)
- Works on every place a card image is shown (My Team roster/bench, the card viewer, the draw reveal) — not just one view

### Jump to a Player or Team From Their Card
**User story**
As a player, I want to click a card's name or team region to go straight to that profile, so that I don't have to search for them separately.

**Acceptance criteria**
- Clicking or activating the player name area of a rendered card opens that player's profile popup
- Clicking or activating the team name or team logo area opens that team's profile popup
- These regions are reachable by keyboard (Tab, then Enter or Space) and are announced to screen readers with a descriptive label
- Clicking anywhere else on the card (photo, stats box, accolade grid, empty margin) still opens the card viewer, exactly as today
- Works both on the small roster/bench grid cards and on the large card-viewer/draw-reveal image

### Consistent Team Logo Fill
**User story**
As a player, I want every team's logo to fill its slot on the card the same way, so that cards look uniform regardless of which team a player is on.

**Acceptance criteria**
- Every team logo fully fills the card's logo box with no visible empty margin on any side, regardless of the source logo's own aspect ratio
- A logo whose aspect ratio doesn't match the box is centre-cropped rather than letterboxed, trading a small edge crop for a consistent fill
- Both the locally cached Dotabuff logo path and the HTTP `team_logo_url` fallback path get the same consistent fill

### Bigger Cards, Five to a Row
**User story**
As a player, I want my roster and bench cards shown larger, five per row, so that I can see them clearly without scrolling sideways.

**Acceptance criteria**
- The active roster grid shows all 5 roster slots in a single row filling the My Team panel's available width, with no horizontal scrollbar
- The bench grid uses the same 5-column layout, wrapping into further rows as it grows past 5 cards
- Cards are visibly larger than the previous fixed 180px width on typical desktop widths
- On narrow/phone-width screens the grid drops to fewer columns so cards stay readable instead of shrinking indefinitely
- The empty-roster-slot and loading placeholders resize the same way as the real card images, so the grid never looks mismatched mid-load

## Implementation

### Critical Files
| File | Change |
|---|---|
| `backend/image.py` | `_ACCOLADE_COUNT_FONT_SIZE` 17→20, `_ACCOLADE_COUNT_BADGE_RADIUS` 11→13; add `_cover_fit()` (scale by `max(w/sw, h/sh)`, centre-crop to the box) and use it only in the team-logo path, leaving `_aspect_fit` (contain) untouched for other callers |
| `backend/routers/cards.py` | Add `team_id` to the `draw_card`, `draw_booster` and `get_card` response dicts (their `team_row` subqueries select `t.name, t.logo_url` only — add `t.id`); `_build_roster_response` and `collection_for_user` already select `t.id as team_id`, no change needed there |
| `frontend/app-globals.js` | New helper mirroring `image.py`'s `_select_accolade_keys`/`_accolade_counts` (same priority tiers, dedupe-first-seen, cap at 6) over the existing `playerAccolades(playerId)`, producing the 6 cell slots with `data-tip` text; reuses the existing `[data-tip]` tooltip engine (`showAccoladeTip`/`_initAccoladeTips`) as-is |
| `frontend/app-roster.js`, `frontend/app-cards.js` | New shared function building the invisible hotspot overlay (accolade cells + name-bar + team region) positioned as percentages of the 687×1024 canvas, laid over `.card-img` in `_cardSlotHTML` and over `#revealCardImg`/`#revealImgWrap` in `showCard`; hotspot click handlers call `openPlayerModal`/`openTeamModal` and `stopPropagation()`; `_onRosterClick` is unaffected since it only fires when the click bubbles past a hotspot |
| `frontend/style.css` | `.card-grid` becomes a 5-column CSS grid (`grid-template-columns: repeat(5, 1fr)`) instead of a horizontally-scrolling flex row; `.card-img` drops its fixed `180px` for `width: 100%`; `.card-img-loading`/`.card-slot-empty` get matching responsive sizing; a `max-width: 768px` breakpoint (matching the existing My Team two-column collapse at line ~1864) drops the column count for narrow screens; new styles for the hotspot overlay elements (invisible, focus-visible outline for keyboard use) |
| `backend/tests/test_card_art_polish.py` | New test file (test-planner stage), including a frontend/backend accolade-priority parity test matching the existing `ACCOLADE_KINDS` parity pattern (`test_issue_230`) |
| `markdown/features/reference/card-image-generation.md` | Updated for the new font/badge-radius constants and the `_cover_fit` team-logo path |
| `markdown/features/reference/card-art-accolade-redesign.md` | Forward-pointer note to this plan |
| `markdown/features/reference/card-draw-animations.md` | Note the reveal modal's card image now carries the same click/hover hotspots as the roster grid |
| `markdown/features/reference/card-art-polish.md` | New reference doc recording this change (see stub) |

No migration, no new env var.

### Step 1 — Accolade badge sizing
In `backend/image.py`, change `_ACCOLADE_COUNT_FONT_SIZE` to `20` and `_ACCOLADE_COUNT_BADGE_RADIUS` to `13`. Re-render a card with a 9+ count locally to confirm the digit no longer touches the circle's edge.

### Step 2 — Team logo cover-fit
Add `_cover_fit(img, w, h)` next to `_aspect_fit` in `backend/image.py`: scale by `max(w / sw, h / sh)`, then crop the centred `w × h` window out of the scaled image. Use it in `_load_team_logo_for_card` (local PNG path) and `_fetch_team_logo_image` → `_fetch_pil_image`'s tuple-size branch (HTTP path) in place of `_aspect_fit`, for the team-logo call only — `_aspect_fit` itself stays as the general-purpose contain-fit helper used elsewhere. Verify by rendering a few real teams' cards (varying logo aspect ratios) and confirming every one fills `_LOGO_BOX` edge-to-edge.

### Step 3 — `team_id` on every card payload that can reach a fresh reveal
Add `t.id as team_id` (or `team.id`) to the `team_row` queries in `draw_card`, `draw_booster`, and `get_card` in `backend/routers/cards.py`, and `"team_id": ...` to their returned dicts, matching the pattern already used in `_build_roster_response`/`collection_for_user`.

### Step 4 — Frontend accolade-selection mirror and tooltip wiring
In `frontend/app-globals.js`, add a helper (e.g. `cardAccoladeSlots(playerId)`) that: dedupes `playerAccolades(playerId)` by kind (first-seen order, matching the existing newest-season-first ordering already used by `accoladeDetailLine`/`accoladePlayedLine`), sorts by the same priority tiers as `image.py`'s `_ACCOLADE_PRIORITY` (champion > runner-up > third > fantasy winner > performance awards > played), caps at 6, and returns each slot's index, `ACCOLADE_KINDS` entry, count, and a formatted tooltip string (reusing `accoladeDetailLine`-style season/value text for the breakdown when count > 1). Add a parity test asserting this priority list matches `image.py`'s `_ACCOLADE_PRIORITY` keys and ordering, the same way `test_issue_230` checks `ACCOLADE_KINDS` parity.

### Step 5 — Hotspot overlay
Add a function building the overlay HTML: one invisible `<span data-tip="...">` per accolade slot from Step 4, positioned via percentages derived from `image.py`'s `_ACCOLADE_COLS`/`_ACCOLADE_ROWS`/`_ACCOLADE_CELL` against the 687×1024 canvas; one focusable `<button>` over `_NAME_BAR`'s percentage region calling `openPlayerModal(playerId)`; one focusable `<button>` spanning `_TEAM_NAME_BAR` + `_LOGO_BOX`'s combined percentage region calling `openTeamModal(teamId)`. Both buttons get an `aria-label`, stop click propagation, and handle Enter/Space. Call this function from `_cardSlotHTML` (`frontend/app-roster.js`) wrapping the existing `<img class="card-img">`, and from `showCard` (`frontend/app-cards.js`) wrapping `#revealCardImg`. Skip the button(s) when the card has no `player_id`/`team_id` (e.g. a slot with no team on record).

### Step 6 — Roster/bench grid layout
In `frontend/style.css`, change `.card-grid` to `display: grid; grid-template-columns: repeat(5, 1fr); gap: 14px;` (drop `overflow-x: auto`); `.card-img` to `width: 100%; height: auto;`; give `.card-img-loading`/`.card-slot-empty` an `aspect-ratio: 687 / 1024` and `width: 100%` instead of their fixed `180×268`. Add a `@media (max-width: 768px)` rule (reusing the existing breakpoint) dropping `.card-grid` to 2 or 3 columns. Confirm `_rosterRects()`/`flipMove` (which read `getBoundingClientRect()` live) still animate correctly with variable card widths — they have no hardcoded pixel assumptions, so this should need no change.

### Step 7 — Docs
Update `card-image-generation.md` for the new constants and `_cover_fit`; add a forward-pointer line in `card-art-accolade-redesign.md`; note the reveal modal's new hotspots in `card-draw-animations.md`; write the new `card-art-polish.md` reference doc (see Phase 3).

## Verification
- `cd backend && python -m pytest tests/ -n auto -q` passes in full, including the new parity test and the rewritten geometry-adjacent tests.
- Render cards for players with 0, 1 and 9+ of the same accolade; confirm the enlarged badge never clips and the tooltip text matches the painted order.
- Click/keyboard-activate the name and team regions on a roster card, a bench card, and a freshly drawn reveal card; confirm each opens the right profile and that clicking the photo/stats still opens the card viewer.
- Render cards for several real teams with different logo aspect ratios; confirm every one fills the logo box with no empty margin.
- Open My Team at a typical desktop width: confirm 5 cards per row with no horizontal scrollbar, then resize to a phone width and confirm the grid drops to fewer columns without cards becoming unreadably small.
