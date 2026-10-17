# Plan: Card Draw Animations

## Context
A draw today opens the reveal modal at once with a placeholder and a rarity burst, then swaps in the card PNG when it has loaded. Nothing connects the result to the deck, and the moment of drawing has no weight. This plan adds two animations to the website:

- **Draw from the deck:** a visible deck in the Draw panel. On a draw, its top card lifts, flies to the centre, flips face up dramatically with the rarity burst, and then the rest of the reveal fades in. The result is the same reveal as today.
- **In My Team:** the deck sits at the top of the Draw sidebar, beside a compact chances strip. After the reveal, Continue sends the card to the place it was added: the open roster slot, or the front of the bench. It lands there with a short rarity glow.
- **Card back (postponed):** a back face with a Flip control in the card viewer. The product owner postponed it on 2026-10-15; it stays as a later story, and the canvas keeps its design.

The draw result and its card image are fetched and decoded before anything moves ("pregenerated"), so the animation never waits mid-flight. A design canvas shows the draw prototype, a storyboard with timings, the My Team integration (desktop prototype and phone layout), and the postponed card back: https://claude.ai/artifact/4xq7DmvxjpJ8m7KxfTz5uB (private until shared).

Assumptions:
- **Website only.** The Twitch panel's in-panel draws keep their current reveal; a panel version is a separate issue.
- **Animation tech.** The card is animated with the Web Animations API (`element.animate`). It starts at the deck's on-screen rectangle and ends at the modal card's rectangle (the FLIP technique), so the motion follows the real layout at any window size. CSS 3D transforms handle the flip.
- **No backend change.** The card PNG stays generated on first request (`GET /cards/{id}/image`). "Pregenerated" means the client loads and decodes it while the deck stirs, before the flight starts. A slow image (over 3 seconds) does not hold the animation: the card flips to its rarity face and the PNG swaps in when ready, as today.
- **League-agnostic card back.** The deck's card back is CSS only: the brand pattern and an emblem, with no league name and no image file.
- **Chances stay.** The four rarity thumbnails become a compact two-by-two strip of coloured dots and percentages beside the deck. The guided tour's Chances step keeps the `.rarity-grid` target.
- **Phone.** Below 768 px the roster sits above the Draw panel. The card flies up off the top edge instead of into an unseen slot. A notice ("Added to active roster", **See roster ↑**) scrolls to the roster, where the new card glows once.
- **Reduced motion.** With `prefers-reduced-motion: reduce`: no flight, flip, burst or landing flight. The finished reveal fades in, and the card simply appears in its slot.
- **Same draw rules.** The draw and booster draw endpoints, their costs and their results are unchanged. Booster draws (Draw from a team) also fly from the deck.

Resolves GitHub issue #205.

## User Stories

### Draw From the Deck
**User story**
As a player, I want to see my card come off the deck and flip over when I draw so that drawing feels like opening a real card.

**Acceptance criteria**
- The Draw panel shows a deck: a small stack of card backs at the top of the Draw panel, beside the Chance per draw strip and above the Draw buttons, decorative only (`aria-hidden`)
- Pressing **Draw a card** or confirming a team draw makes the deck stir (a slight wobble) until the draw result has arrived and its card image is loaded and decoded, or 3 seconds have passed
- Then the deck's top card lifts (about 220 ms), flies to the centre of the screen while the page dims (about 460 ms), and flips face up on its vertical axis with a slight overshoot (about 520 ms). The rarity burst plays behind it in the card's rarity colour
- After the flip, the rest of the reveal fades in: rarity label, destination ("Added to active roster" / "Added to bench"), Reroll and Continue (about 400 ms). The finished modal is the same as today's draw reveal
- A failed draw (no tokens, roster full, server error) plays no animation and shows the error as today
- If the image is not ready after 3 seconds, the card still flies and flips to its rarity face; the PNG appears when it loads. An image error shows today's rarity fallback text
- Pressing Draw again during the animation does nothing (the button stays busy until the reveal is shown)
- With reduced motion, there is no flight, flip or burst: the finished reveal fades in after the result and image are ready

### Deck in My Team
**User story**
As a player, I want the deck and the drawn card to fit the My Team page so that I see where my new card went.

**Acceptance criteria**
- The Draw sidebar starts with the deck (three stacked card backs) beside a compact **Chance per draw** strip: four coloured dots with the rarity name and its percentage, from the same `draw_rate_*` weights as today
- The Draw buttons, hint, promo code and status line stay below, unchanged
- After the reveal, **Continue** closes the modal and the card flies to where it was added: the open roster slot (when the reveal says "Added to active roster") or the front of the bench ("Added to bench"), shrinking to the slot size (about 520 ms). It then glows once in its rarity colour (about 1.2 s), and the roster count and bench update as today
- **Draw another card** in the reveal skips the landing and starts the next draw from the deck
- Closing the reveal another way (✕, Escape, backdrop) skips the landing flight; the roster updates as today
- On a phone (below 768 px), the card flies up off the top edge. A notice "Added to active roster" / "Added to bench" with **See roster ↑** appears for 5 seconds; See roster scrolls to the roster, and the new card glows once
- With reduced motion, there is no landing flight: the card appears in its slot with the glow

### Flip a Card to Its Back *(not yet implemented)*
**User story**
As a player, I want to flip any card I'm viewing to see its back so that the card feels like a physical object and can later show more about it.

**Acceptance criteria**
- The card viewer (the reveal modal, opened from a draw, My Team, the Weekly Report or the own-player notice) has a **Flip card** button under the card image, and clicking the card image does the same
- Flip turns the card 180° on its vertical axis (about 600 ms) to show the back; the button then reads **Show front** and has `aria-pressed="true"`; flipping again shows the front
- The back is a placeholder: the same pattern and emblem as the deck, the words "Card back", no league name
- Every card opens front side up; closing the viewer resets it
- With reduced motion, Flip swaps the faces without rotating
- Keyboard: the Flip button and the card image are focusable and work with Enter and Space

### Card Back Ready for More *(not yet implemented)*
**User story**
As a player, I want the back of a card to show its stats or accolades so that I can see what a card has done for me.

**Acceptance criteria**
- The back shows either per-card stats (matches scored, points with this card, average, best match, modifiers) or accolades (MVP picks, weekly bests), as on the canvas's "Later" designs
- Needs the flip from the story above; the data comes from stored per-match card points

## Implementation

### Critical Files
| File | Change |
|---|---|
| `frontend/index.html` | Deck stack (`#drawDeck`) at the top of the Draw panel beside the compact chances strip (`.rarity-grid` kept); a phone notice (`#drawLandedNotice`) |
| `frontend/app-cards.js` | `drawCard()` and the booster draw: deck stir, `_prepareDrawnCard(card)` (image preload and decode, 3 s cap), `_playDrawFlight(card)` (Web Animations from the deck to the modal card), then today's `showReveal`; `_playLandingFlight(card)` on Continue |
| `frontend/app-roster.js` | Expose the rectangle of the slot a card went to (open roster slot or bench front) and a one-time rarity glow on the card that arrived (`markArrived(cardId)`) |
| `frontend/style.css` | Deck and card-back styles from the brand tokens, flip faces (`backface-visibility`), stir and fade-in keyframes, `prefers-reduced-motion` overrides |
| `markdown/ui_description/my-team.md` | Deck and chances strip in the Draw panel; draw animation; landing in the roster or bench; phone notice |
| `markdown/features/reference/card-draw-animations.md` | Feature doc |
| `backend/tests/test_issue_205_card_draw_animations.py` | Static checks and a Node harness for the draw sequence |

### Step 1 — Card back style (`style.css`)
- `.card-back`: the brand pattern and emblem, as CSS only. It is used by the deck and by the flight's back face.
- The future flip reuses it.

### Step 2 — Deck and chances strip (`index.html`, `style.css`)
- A stack of three `.card-back` layers at the top of the Draw panel, `aria-hidden="true"`.
- The rarity grid becomes a compact two-by-two strip beside it, keeping the `.rarity-grid` class and the `#deck-*` ids.
- A `.draw-deck--stirring` class plays a small rotate/translate loop.
- The deck hides on narrow screens if it crowds the buttons. The flight then starts from the Draw button.

### Step 3 — Draw sequence (`app-cards.js`)
```js
async function drawCard() {          // booster draw follows the same path
  // withBusy as today; deck stirs while waiting
  const data = await postDraw();     // unchanged request and error handling
  await _prepareDrawnCard(data);     // load + decode cardImageUrl(id), resolve at 3 s at the latest
  if (_prefersReducedMotion()) return showReveal(data);         // plus a fade-in class
  await _playDrawFlight(data);       // lift, travel, flip; returns when the card sits at the modal card's place
  showReveal(data, …, { entering: true });                       // details fade in; burst as today
}
```
- `_playDrawFlight` builds a fixed-position clone (`.draw-flight`) with the back and the prepared PNG as its two faces.
- The clone is measured from `#drawDeck` and the modal card's rectangle. The modal is opened invisibly for measuring, with its frame elements at opacity 0.
- The clone runs three `animate()` calls (lift, travel, flip), then is removed. The real modal card shows in the same place, so the hand-off is seamless.
- Keep `DRAW_REVEAL_MIN_MS` and the existing burst, but trigger the burst at flip time.

### Step 3b — Landing (`app-cards.js`, `app-roster.js`)
- On Continue (`revealAction`), after `loadRoster` has rendered, read the target slot's rectangle:
  - the card's roster slot when `is_active`, else the first bench card;
  - on a phone, or when the slot is off screen, a point above the viewport.
- Animate a clone of the modal card there (about 520 ms), remove it, and call `markArrived(card.id)` for the glow.
- On a phone, show `#drawLandedNotice` for 5 seconds; its **See roster ↑** scrolls `#rosterActiveGrid` into view.
- Draw another card, ✕, Escape and the backdrop skip the landing.

### Step 4 — Docs and tests
- **Docs:** update `ui_description/my-team.md` and the feature doc.
- **Static tests:**
  - deck markup is `aria-hidden`;
  - `.rarity-grid` and the `#deck-*` ids are kept;
  - the `prefers-reduced-motion` rules cover the flight, flip, stir and landing;
  - the card back has no league name or image file.
- **Node harness tests** (fake DOM, stubbed `fetch`, `Image` and `animate`):
  - the flight starts only after the image is decoded;
  - it starts at 3 s with a slow image;
  - a failed draw plays no flight;
  - reduced motion skips `animate`;
  - Draw stays busy until the reveal shows;
  - Continue lands on the roster slot when `is_active` and on the bench front otherwise;
  - Draw another card and ✕ skip the landing;
  - a phone width shows the notice.

## Verification
- `cd backend && python -m pytest tests/test_issue_205_card_draw_animations.py`
- Manual, in a browser:
  - Draw a card and a team card: the deck stirs, the card flies and flips, then the reveal fades in, and the result matches the server's card.
  - Throttle the network to "Slow 3G": the flight waits for the image, or starts after 3 s.
  - Try a draw with no tokens: no animation, error shown.
  - Turn on the OS reduced-motion setting: fade only.
  - After Continue, the card lands in the open roster slot, or at the bench front when the roster is full, and glows once.
  - On a phone, the notice appears and See roster scrolls up to the glowing card.
  - Check at 360 px width and with the keyboard only.
- No migration, no env vars.
