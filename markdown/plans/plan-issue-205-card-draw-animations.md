# Plan: Card Draw Animations

## Context
A draw today opens the reveal modal at once with a placeholder and a rarity burst, then swaps in the card PNG when it has loaded. Nothing connects the result to the deck, and the moment of drawing has no weight. This plan adds two animations to the website:

- **Draw from the deck:** a visible deck in the Draw panel. On a draw, its top card lifts, flies to the centre, flips face up dramatically with the rarity burst, and then the rest of the reveal fades in. The result is the same reveal as today.
- **Card back:** a back face on every card in the card viewer, with a Flip control. For now the back is a placeholder; later it can hold stats or accolades.

The draw result and its card image are fetched and decoded before anything moves ("pregenerated"), so the animation never waits mid-flight. A design canvas shows both animations with working prototypes, a storyboard with timings, and the card back now and later: https://claude.ai/artifact/4xq7DmvxjpJ8m7KxfTz5uB (private until shared).

Assumptions:
- **Website only.** The Twitch panel's in-panel draws keep their current reveal; a panel version is a separate issue.
- **Animation tech.** The card is animated with the Web Animations API (`element.animate`). It starts at the deck's on-screen rectangle and ends at the modal card's rectangle (the FLIP technique), so the motion follows the real layout at any window size. CSS 3D transforms handle the flip.
- **No backend change.** The card PNG stays generated on first request (`GET /cards/{id}/image`). "Pregenerated" means the client loads and decodes it while the deck stirs, before the flight starts. A slow image (over 3 seconds) does not hold the animation: the card flips to its rarity face and the PNG swaps in when ready, as today.
- **League-agnostic back.** The placeholder back is CSS only: the brand pattern and an emblem, with no league name and no image file.
- **Reduced motion.** With `prefers-reduced-motion: reduce`: no flight, flip or burst. The finished reveal fades in, and the Flip control swaps faces without rotating.
- **Same draw rules.** The draw and booster draw endpoints, their costs and their results are unchanged. Booster draws (Draw from a team) also fly from the deck.

Resolves GitHub issue #205.

## User Stories

### Draw From the Deck
**User story**
As a player, I want to see my card come off the deck and flip over when I draw so that drawing feels like opening a real card.

**Acceptance criteria**
- The Draw panel shows a deck: a small stack of card backs next to the Draw buttons, decorative only (`aria-hidden`)
- Pressing **Draw a card** or confirming a team draw makes the deck stir (a slight wobble) until the draw result has arrived and its card image is loaded and decoded, or 3 seconds have passed
- Then the deck's top card lifts (about 220 ms), flies to the centre of the screen while the page dims (about 460 ms), and flips face up on its vertical axis with a slight overshoot (about 520 ms). The rarity burst plays behind it in the card's rarity colour
- After the flip, the rest of the reveal fades in: rarity label, destination ("Added to active roster" / "Added to bench"), Reroll and Continue (about 400 ms). The finished modal is the same as today's draw reveal
- A failed draw (no tokens, roster full, server error) plays no animation and shows the error as today
- If the image is not ready after 3 seconds, the card still flies and flips to its rarity face; the PNG appears when it loads. An image error shows today's rarity fallback text
- Pressing Draw again during the animation does nothing (the button stays busy until the reveal is shown)
- With reduced motion, there is no flight, flip or burst: the finished reveal fades in after the result and image are ready

### Flip a Card to Its Back
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
- The data comes from stored per-match card points; the front and the flip stay as built in this plan

## Implementation

### Critical Files
| File | Change |
|---|---|
| `frontend/index.html` | Deck stack in the Draw panel (`#drawDeck`); reveal image area restructured into a flip container with front (`#revealCardImg` and placeholder) and back faces; **Flip card** button (`#cardFlipBtn`) |
| `frontend/app-cards.js` | `drawCard()` and the booster draw: deck stir, `_prepareDrawnCard(card)` (image preload and decode, 3 s cap), `_playDrawFlight(card)` (Web Animations from the deck to the modal card), then today's `showReveal`; `toggleCardFlip()`, reset in `showCard()` and `closeReveal()` |
| `frontend/style.css` | Deck and card-back styles from the brand tokens, flip faces (`backface-visibility`), stir and fade-in keyframes, `prefers-reduced-motion` overrides |
| `markdown/ui_description/my-team.md` | Deck in the Draw panel; draw animation; Flip in the card viewer |
| `markdown/features/reference/card-draw-animations.md` | Feature doc |
| `backend/tests/test_issue_205_card_draw_animations.py` | Static checks and a Node harness for the draw sequence |

### Step 1 — Card back and flip (`index.html`, `style.css`, `app-cards.js`)
```html
<div class="reveal-img-wrap card-flip" id="revealImgWrap">
  <button type="button" class="card-flip-inner" id="cardFlipInner" onclick="toggleCardFlip()" aria-label="Flip card">
    <span class="card-face card-face--front"><!-- placeholder + #revealCardImg as today --></span>
    <span class="card-face card-face--back" aria-hidden="true"><span class="card-back">…</span></span>
  </button>
</div>
<button type="button" class="ghost" id="cardFlipBtn" onclick="toggleCardFlip()" aria-pressed="false">Flip card</button>
```
- `toggleCardFlip()` toggles `.is-flipped` on the flip container and sets the button label and `aria-pressed`.
- `showCard()` and `closeReveal()` remove `.is-flipped`.
- The `.card-back` pattern is shared with the deck.

### Step 2 — Deck (`index.html`, `style.css`)
- A stack of three `.card-back` layers beside the Draw buttons, `aria-hidden="true"`.
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

### Step 4 — Docs and tests
- **Docs:** update `ui_description/my-team.md` and the feature doc.
- **Static tests:**
  - deck markup is `aria-hidden`;
  - the flip button and `toggleCardFlip` exist;
  - `showCard` resets the flip;
  - the `prefers-reduced-motion` rules cover the flight, flip and stir;
  - the back has no league name or image file.
- **Node harness tests** (fake DOM, stubbed `fetch`, `Image` and `animate`):
  - the flight starts only after the image is decoded;
  - it starts at 3 s with a slow image;
  - a failed draw plays no flight;
  - reduced motion skips `animate`;
  - Draw stays busy until the reveal shows.

## Verification
- `cd backend && python -m pytest tests/test_issue_205_card_draw_animations.py`
- Manual, in a browser:
  - Draw a card and a team card: the deck stirs, the card flies and flips, then the reveal fades in, and the result matches the server's card.
  - Throttle the network to "Slow 3G": the flight waits for the image, or starts after 3 s.
  - Try a draw with no tokens: no animation, error shown.
  - Turn on the OS reduced-motion setting: fade only.
  - Open a card from My Team and from the Weekly Report: Flip shows the back and Show front returns. Closing and reopening shows the front.
  - Check at 360 px width and with the keyboard only.
- No migration, no env vars.
