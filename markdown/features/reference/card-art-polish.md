# Card Art Polish

Five follow-up refinements to the [Card Art Accolade Redesign](card-art-accolade-redesign.md), found by testing the shipped templates with real data: bigger, more informative accolade badges, click-through from the card face to a player's or team's profile, consistent team-logo fill, and bigger My Team roster/bench cards. Plan: `markdown/plans/plan-card-art-polish.md`.

---

## Accolade badges: bigger count, hover tooltip

The accolade count badge (`backend/image.py::_draw_accolade_count_badge`) grows its digit size and circle radius: `_ACCOLADE_COUNT_FONT_SIZE` 17→20, `_ACCOLADE_COUNT_BADGE_RADIUS` 11→13, so a "9+" count no longer crowds the edge.

Since the accolades are baked into a flat PNG, hovering an individual badge needs an invisible overlay on top of the `<img>`. `frontend/app-globals.js`'s `cardAccoladeSlotsFromList(accoladesList)` (and `cardAccoladeSlots(playerId)`, which reads it from the loaded `playerAccolades(playerId)` cache) mirrors `image.py`'s accolade selection rule exactly: dedupe by `ACCOLADE_KINDS` key keeping the first-seen (newest) occurrence, rank by `_CARD_ACCOLADE_PRIORITY` (a frontend copy of `image._ACCOLADE_PRIORITY`, parity-tested the same way as `ACCOLADE_KINDS`), cap at 6. Each returned slot carries a `tip`/`aria` string built from the existing `_accoladePipText` helper (same breakdown text as the pip tooltips: the accolade name and, when held more than once, the count and seasons). `cardHotspotOverlayHtml(c)` turns each slot into an invisible `<span data-tip="…" tabindex="0">` positioned over its cell, reusing the existing generic tooltip engine (`[data-tip]`, `showAccoladeTip`/`_initAccoladeTips`) — no new tooltip UI. These accolade spans carry no click handler, so a tap still bubbles up to the card's own "open card viewer" behaviour, same as before.

These new helpers live just after the `// END ACCOLADES (issue 50)` marker in `app-globals.js`, deliberately outside the `// ACCOLADES (issue 50)` … `// END ACCOLADES (issue 50)` block: several existing tests load that whole block as a Node harness, and growing it pushed the generated script past the OS command-line length limit in CI.

## Click-through from the card face

`cardHotspotOverlayHtml(c)` also returns one focusable `<button>` over the player name-bar region (`openPlayerModal(playerId)`) and two over the team name-bar and logo-box regions (`openTeamModal(teamId)`, same handler on both so either spot works) — each with an `aria-label`, each stopping the click's propagation so it never also triggers the card's own "open card viewer" behaviour. Buttons are left out when the card has no `player_id`/`team_id`. All geometry is percentages of the 687×1024 canvas, taken directly from `image.py`'s `_NAME_BAR`/`_TEAM_NAME_BAR`/`_LOGO_BOX`/`_ACCOLADE_COLS`/`_ACCOLADE_ROWS`/`_ACCOLADE_CELL` (kept in lock-step; a test checks the frontend and backend rects match).

`frontend/app-roster.js`'s `_cardSlotHTML` wraps `<img class="card-img">` in a `.card-img-wrap` (`position: relative`) and appends the overlay — covers My Team roster and bench. `frontend/app-cards.js`'s `showCard` fills `#revealCardHotspots` (a sibling of `#revealCardImg` inside `#revealImgWrap`) the same way on every call — covers the card viewer and the draw reveal. The hotspot regions (name bar, team bar, logo box) never geometrically overlap the photo slot or stats box, so a click there still bubbles to the existing "open card viewer" handler unmodified.

`backend/routers/cards.py`'s `draw_card`, `draw_booster` and `get_card` each add `t.id as team_id` to their `team_row` subquery and `"team_id"` to the returned dict, alongside the existing `team_name`/`team_logo_url` — needed so the draw reveal's freshly-returned card has a team id to pass to `openTeamModal`. `_build_roster_response`/`collection_for_user` already selected `team_id`.

## Consistent team-logo fill

The team-logo slot switches from contain-fit (`_aspect_fit`, which can letterbox unevenly depending on a given logo's own aspect ratio) to a new `_cover_fit(img, w, h)` helper next to `_aspect_fit`: scale by `max(w/sw, h/sh)` so the box is fully covered, then centre-crop to exactly `w × h`. Used in both team-logo paths — `_load_team_logo_for_card`'s local-PNG branch and `_fetch_pil_image`'s tuple-size branch (which `_fetch_team_logo_image`, the HTTP fallback, is the only caller of) — so every team's logo now fully fills the slot either way. `_aspect_fit` itself is unchanged and still used for the player photo's own resize-to-fill and the accolade badge icons.

## Roster/bench cards: five per row

`#rosterActiveGrid`/`#benchGrid` (`.card-grid`) become a 5-column CSS grid (`grid-template-columns: repeat(5, 1fr)`) instead of a horizontally-scrolling flex row (`overflow-x: auto` dropped). `.card-img` drops its fixed `180px` for `width: 100%; height: auto`; `.card-img-loading`/`.card-slot-empty` get `aspect-ratio: 687 / 1024; width: 100%` in place of the old fixed `180×268`, so a placeholder is sized identically to the real card image. The active grid (5 roster slots) shows one full row with no scrollbar; the bench wraps into further rows automatically (CSS grid's default auto-placement, no explicit row count). The existing `@media (max-width: 768px)` breakpoint (already used to collapse the My Team two-column layout) adds a `.card-grid` rule dropping to 2 columns on phone widths.

## Tests

`backend/tests/test_card_art_polish.py`. Frontend checks reuse the Node-harness pattern of `test_issue_50`/`test_issue_228` (`_fe`, `_rule`, `_css_blocks`, `_run_node`, `_fn_source`, `_a`, `_globals_helpers_js`); image checks reuse `_image`, `_render` from `test_issue_228`.

## Plan

`markdown/plans/plan-card-art-polish.md`
