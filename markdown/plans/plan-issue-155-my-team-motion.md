# Plan: My Team Motion

## Context
Issue #155 asks where animations could go now that the Weekly Report has its recap animation (#152), most likely on My Team. It asks for mockups to propose ideas; a comment asks for them on a canvas.

**My Team's motion today:**
- the draw reveal (blur, flash and shimmer);
- drag-and-drop pulses on empty slots and the bench;
- a 180 ms "card-settle" after a re-render;
- the reroll image flash.

Everything else changes instantly:
- points that arrive after a match is ingested;
- moving a card between bench and roster;
- the week locking;
- bench substitutions;
- token changes.

These are the moments where something happened to the player's team while they weren't looking, and they're the best places for motion.

The proposals, each mocked as a playable artboard on the canvas: https://claude.ai/artifact/4ThcdkKcxMYAKRZ1DztuPZ
1. **New points since your last visit:** the roster cards' points count up, and the week total follows.
2. **Bench ↔ roster move:** the card slides to its new slot instead of jumping. *Moved to #186* (local layout, pointer drag, autosave), see below.
3. **Week locks:** a short lock stamp the first time you open a newly locked week.
4. **Substitution reveal:** the first time you view a week after its bench substitutions ran, the subbed-out card drops to the bench and the substitute rises into its slot.
5. **Token gain:** the header token chip counts up and pulses when the balance rises (MVP drop, weekly token, starter, promo).

Principles, from #152:
- **Short:** each animation is short (≤ 1.2 s, except the count-ups, which are capped at 2 s).
- **Once:** each plays once per event (remembered per browser in `localStorage`, every access in try/catch).
- **Skippable:** each finishes instantly on click.
- **Reduced motion:** nothing moves with `prefers-reduced-motion: reduce`; the final state just shows.
- **No new backend data:** the page compares what it shows now with what it showed last time.

Assumption: four are in scope here (1, 3, 4, 5); idea 2 is planned with #186. Stories 1 and 4 add the most information. If you want fewer, name the ones to drop (`/ship sync 155` narrows the issue) before `/develop`.

Resolves GitHub issue #155.

## User Stories

### New Points Count Up Since Your Last Visit
**User story**
As a player, I want to see which of my cards scored since I last looked, so that new results feel like an event and not a silently changed number.

**Acceptance criteria**
- My Team remembers, per user and week, the points it last showed for each roster card and the week total (`localStorage` key `rosterSeenPoints:<user id>:<week id>`)
- When a card's points are higher than last time:
  - its number counts up from the old value to the new one (ease-out, `clamp(600 + delta × 20, 600, 2000)` ms);
  - a floating "+delta" in the accent colour rises above it;
  - its slot glows briefly.
- The week total counts up in step, and ends at the server's value
- No animation on the first visit to a week (nothing stored yet), for locked weeks shown for the first time, or for decreases (a corrected score): the value just updates
- With reduced motion, the values update instantly. Clicking anywhere on the roster finishes the count-ups
- The final numbers are always the server's values; screen readers get the final value only (`aria-hidden` on the counting text)

### Cards Slide Between Bench and Roster *(moved to #186)*
Planned in `markdown/plans/plan-issue-186-my-team-save-roster.md`: moves apply locally and glide into place, dragging follows the pointer with a live preview (also on touch), and the layout autosaves. Doing it there avoids animating around today's request-then-redraw flow, which would have to be replaced anyway. The shared `flipMove()` and `prefersReducedMotion()` helpers are built once, by whichever of #155 and #186 is developed first.

### The Week Lock Has a Moment
**User story**
As a player, I want to notice that my roster for the week is now locked, so that I know my lineup counts from here.

**Acceptance criteria**
- The first time a user opens a week on My Team after it has locked, the "Roster locked" banner stamps in: it scales from 1.15 to 1 and fades in over 300 ms, with a lock icon that closes. The roster cards dim to their locked style over 400 ms.
- This plays once per user and week (`localStorage` `rosterLockSeen:<user id>`, keeping the last 50 week ids)
- Later visits, and reduced motion, show the locked state directly

### Substitutions Play Out Once
**User story**
As a player, I want to see the bench substitutions happen, so that I understand why a bench card scored for me.

**Acceptance criteria**
- The first time a user views a locked week after its substitutions ran (`substitutions_at` set and at least one substitution), each substitution plays in roster order:
  - the subbed-out card slides down and fades to the bench area;
  - the substitute rises into its slot;
  - the "Subbed in for {player}" label fades in.
  - About 700 ms per substitution, 300 ms apart.
- It plays once per user and week (`localStorage` `rosterSubsSeen:<user id>`). A re-run that changes the substitutions (for example after an admin week change, #193) plays the new result once again.
- Clicking finishes it at once; with reduced motion the final state shows directly

### Token Gains Are Noticed
**User story**
As a player, I want to notice when I receive tokens, so that MVP drops and grants don't pass by unseen.

**Acceptance criteria**
- **When it plays:** when `updateTokenDisplay` sets a balance higher than the one shown before (any source), the header token number counts up over 600 ms and the chip pulses once with a floating "+N".
- **What doesn't animate:**
  - spending tokens (a draw) updates instantly;
  - the first display after page load animates only if the balance rose since the value last stored for this user (`localStorage` `tokensSeen:<user id>`).
- **Reduced motion:** instant.

## Implementation

### Critical Files
| File | Change |
|---|---|
| `frontend/app-roster.js` | Seen-points store, count-ups, lock stamp, substitution playback, one shared cancel/finish handle (moves: #186) |
| `frontend/app-globals.js` | `updateTokenDisplay`: rise detection, count-up, pulse; a small shared `motion` helper (reduced-motion check, a `localStorage` wrapper with try/catch, `tweenNumber`, `flip`) |
| `frontend/style.css` | Keyframes and classes for points glow and float, the lock stamp, the substitution slide and the token pulse, all switched off under `prefers-reduced-motion` (placed before the GUIDED TOUR section; lessons-learned) |
| `markdown/ui_description/my-team.md`, `markdown/features/reference/my-team-drag-and-drop.md`, `markdown/features/reference/weekly-recap-animations.md` (shared motion principles) | Existing docs |
| `backend/tests/test_issue_155_my_team_motion.py` | Static and Node-harness tests |

No backend change, no schema change, no env var.

### Step 1 — Shared motion helper
- **Where:** in `app-globals.js`.
- **Functions:**
  - `prefersReducedMotion()`;
  - `seenStore(key)` (get and set with try/catch, capped lists);
  - `tweenNumber(el, from, to, ms)` (`requestAnimationFrame`, returns a finish function);
  - `flipMove(elements, mutate)` (record rects, mutate, invert, play).
- **Cancellation:** a `runId` per animation group, as `_recapAnimation` does in #152.

### Step 2 — Roster stories
- **Points:** in `loadRoster`, after rendering, compare with the seen store and run the count-ups.
- **Moves:** wrap the DOM update after a confirmed move in `flipMove`.
- **Lock and substitutions:** check the seen stores when a locked week renders.
- **Finishing:** one click handler on the roster finishes everything that is running.

### Step 3 — Token chip
`updateTokenDisplay(balance)` compares with the currently shown number and the stored value.

### Step 4 — Docs and tests
**Docs:** a short "Motion" section in `my-team.md`, the FLIP note in `my-team-drag-and-drop.md`, and the shared principles linked from `weekly-recap-animations.md`.

**Tests**, through the Node harness where the code is pure, otherwise static checks:
- the seen-store keys and caps;
- no animation on first visit or on decreases;
- the final values equal the server values;
- every keyframe class is disabled under `prefers-reduced-motion`;
- `tweenNumber` ends at its target;
- FLIP runs only after a successful response.

## Verification
- **Points:** on test, ingest a match for a rostered player while My Team is open in another tab. Reload: that card counts up with "+points", and the week total follows. Reload again: no animation.
- **Moves:** drag a bench card onto the roster; it slides, and the displaced card slides to the bench. Force an error (rate limit): nothing moves.
- **Lock:** advance the demo clock past a lock and open My Team; the stamp plays once.
- **Substitutions:** on a week with substitutions, the swap plays once. After an admin week change that re-runs them (#193), it plays again.
- **Tokens:** an MVP drop or promo code counts the chip up; a draw doesn't animate.
- **Reduced motion:** with reduced motion on in the OS, nothing moves anywhere, and the final states are correct.
- **Tests:** `cd backend && python -m pytest tests/test_issue_155_my_team_motion.py -q`, then `python -m pytest tests/ -n auto -q`.
