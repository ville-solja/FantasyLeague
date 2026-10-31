# Card Draw Animations

On the website, a drawn card comes off a deck in the Draw panel, flies to the centre and flips face up with the rarity burst. The rest of the reveal then fades in, and on Continue the card lands in the roster slot or bench place it was added to (issue #205). A card back with a Flip control is postponed. Plan: `markdown/plans/plan-issue-205-card-draw-animations.md`. Design canvas: https://claude.ai/artifact/4xq7DmvxjpJ8m7KxfTz5uB.

Frontend only: no endpoints, tables or env vars change. The draw endpoints (`POST /draw`, `POST /draw/booster/{team_id}`), their costs and results are unchanged. The Twitch panel keeps its own reveal.

---

## Draw sequence

`drawCard()` and the team draw `_drawBoosterForTeam(teamId)` in `frontend/app-cards.js` follow the same path:

1. **Stir:** `#drawDeck` gets `.draw-deck--stirring` (a small wobble of its top cards) from the press until the draw has answered and `_prepareDrawnCard(card)` has loaded and decoded the card PNG (`GET /cards/{id}/image`), for `DRAW_PREPARE_MAX_MS` (3 s) at most. It resolves `{ state, src }` with state `ready`, `slow` (3 s passed; the image keeps loading), `error` or `none`. The team picker hides as soon as the team draw answers, so the deck is visible.
2. **Open, invisibly:** `showReveal(card, teamId)` opens the reveal with `.reveal-overlay--entering`: a transparent backdrop, and the card frame and its contents hidden but laid out, so the card's place can be measured. The card image is hidden by its own rule too (`.reveal-overlay--entering .reveal-img-wrap .reveal-card-img`), because its base rule sets `visibility: visible`. When the image has decoded, `showCard` clears its inline `visibility` instead of setting it to `visible`, because an inline value would override that rule. The real card at the resting place therefore stays hidden until the flying card has arrived and finished its flip, and no duplicate shows behind it.
3. **Lift, travel, flip:** `_playDrawFlight(card, prep)` builds a fixed `.draw-flight` clone at the reveal card's rectangle (`#revealImgWrap`), with a front face (the decoded PNG, or a rarity face when the image is slow or failed) and a `.card-back` back face. It starts from the deck's rectangle (FLIP: a translate and scale from the deck to the clone's place) and runs two Web Animations (`element.animate`):
   - **move, 680 ms, one continuous animation:** up 24 px with a slight tilt in the first 220 ms (keyframe offset 220/680), then to the reveal card's place. One easing over the whole move (`DRAW_MOVE_EASE`, `cubic-bezier(0.45, 0, 0.2, 1)`) starts gently from the deck and never stops between the lift and the travel. The backdrop dims (`.reveal-overlay--dim`) as the move starts.
   - **flip, 520 ms,** starting 120 ms before the card arrives (`DRAW_FLIP_OVERLAP_MS`): the inner layer turns from `rotateY(180deg)` to face up with a slight overshoot. The rarity burst (`_playDrawBurst`, the existing `.reveal-draw-burst`) starts with the flip, behind the card.

   The clone's back face gets `font-size` = 16px × reveal width ÷ deck width (a leftover of the pre-redesign CSS-pattern back; harmless now that the back face is a fixed image). The back face shows `assets/card_templates/Card_Back.png` (`background-size: contain`), which reads as the same object as the deck it just left.
4. **Details:** the clone is removed where the real reveal card now shows, and `.reveal-overlay--details-in` fades in the frame, rarity label, destination ("Added to active roster" / "Added to bench"), Reroll and Continue (400 ms, the details 120 ms after the frame). The finished modal is the same reveal as before.
5. **Roster reload:** `loadRoster` runs after the flight (kept in `_drawRosterReload`), so the new card doesn't appear in its slot while the card is still on its way.

The Draw button (`withBusy`) and the team draw's `_boosterDrawInFlight` flag stay set until the reveal shows, so a second press sends no second draw (#185). `revealAction()` (Continue, Draw another card, Enter) does nothing while the reveal is still entering.

- **Failed draw** (no tokens, roster full, 429, server or network error): the deck stops stirring, nothing animates, no reveal opens, and the error shows in `#deckStatus` as before.
- **Slow image:** after 3 s the card flies anyway and flips to its rarity face; the reveal keeps that face (the rarity name) until the PNG loads, then shows the PNG.
- **Image error:** the card flies with its rarity face, and the reveal shows the rarity fallback text as before.
- **No Web Animations API** (old browsers, test harnesses) or nothing to measure: no clone and no error; the reveal shows at once with the burst and the details fade-in.

## Landing in My Team

- **Continue** (`revealAction` when the balance can't pay for another draw): `_takeRevealLanding()` takes the reveal card's rectangle and image before the modal closes. `_playLandingFlight` waits for `_drawRosterReload`, then asks `rosterArrivalSlot(card)` in `frontend/app-roster.js` for the target: the card's own `.card-slot` node, else the open roster slot (`is_active`) or the front of the bench. A fixed `.draw-landing` clone flies there (520 ms) while the slot is hidden, then `markArrived(card.id)` adds `.card-slot--arrived`: one glow in the card's rarity colour (`--arrive-glow` from `data-rarity`, 1.2 s, `ROSTER_ARRIVED_MS`).
- **Slot missing or off screen:** the clone flies to a point above the top edge; the glow still plays on the card if it is in the grids.
- **Draw another card** closes the reveal and starts the next draw from the deck; no landing. **✕** and **Escape** (`closeReveal`) and a backdrop click close it without a landing; the roster reload runs as before.
- **Phone** (`window.innerWidth` below 768 px, where the roster sits above the Draw panel): the card flies up off the top edge, and `#drawLandedNotice` shows "Added to active roster" or "Added to bench" with **See roster ↑** for 5 seconds. See roster (`seeLandedCard()`) scrolls `#rosterActiveGrid` into view and plays the glow.

## Draw panel

"Deck" here means the picture of stacked card backs; it is unrelated to `GET /deck`, which counts the player-and-rarity combinations still to draw (`core/cards.md`). The Draw sidebar starts with `.draw-top`: the deck (`#drawDeck`, `aria-hidden="true"`, three stacked `.card-back.draw-deck-layer` layers) beside the **Chance per draw** strip. The strip is a two-by-two `.rarity-grid` of `.rarity-chance` entries: a dot in the rarity colour, the rarity name and the percentage in `#deck-common`, `#deck-rare`, `#deck-epic`, `#deck-legendary`, filled by `loadDeck()` from `GET /config` → `draw_rates`. The guided tour's Chances step still targets `.rarity-grid`.

The base `.card-back` class (`frontend/style.css`) is still CSS only — a cross-hatch in `--accent-ghost` on `--k-ink-900` and a diamond emblem in `--accent` from `::before` / `::after`, sized in em from a 16px base — but neither current use of it shows that pattern any more: `.draw-deck-layer` overrides it with `assets/card_templates/Card_Deck.png` (the deck art, which bakes in its own stacked-edge shadow) and `.draw-flight-face--back` overrides it with `assets/card_templates/Card_Back.png` (a single card's back, no stack shadow), both via `background-size: contain` with the border and `::before`/`::after` emblem suppressed. The plain CSS pattern remains the fallback for `.card-back` on its own, ready for the postponed Flip-card-to-back feature below.

## Reduced motion

With `prefers-reduced-motion: reduce`: no stir, flight, flip, burst or landing flight. The reveal opens with `.reveal-overlay--fade-in` (opacity only, 400 ms) once the result and image are ready, and on Continue the arrived card shows a still rarity ring for 1.2 s instead of the animated glow. The CSS media block also stops `.draw-flight`, `.draw-flight-inner`, `.draw-flight-face`, `.draw-landing` and `.draw-deck--stirring` animations.

## Card back *(postponed)*

A Flip control in the card viewer, with a placeholder back that could later show stats or accolades. The design is on the canvas; `.card-back` is ready for it.

## Tests

`backend/tests/test_issue_205_card_draw_animations.py`: static checks of the markup and CSS, and a Node harness that runs `app-cards.js` with a fake DOM, timers, `fetch`, `Image` and `Element.prototype.animate`. The Playwright tests in `tests/ui/test_card_draw.spec.js` and `tests/ui/test_roster.spec.js` still pass: the reveal counts as visible while it is entering, and ✕ / Escape close it at any time.
