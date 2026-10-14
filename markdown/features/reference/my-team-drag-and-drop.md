# My Team — Drag-and-Drop Roster Ordering

Drag-and-drop on the My Team tab: reorder cards within the active roster or bench, and move
cards between zones by dragging. Also adds backdrop-click dismissal for the card viewer modal.
Since #186 the drag uses Pointer Events (mouse, pen and touch), applies every move locally and
autosaves the layout with `PUT /roster`; see [My Team Fluid Roster](my-team-save-roster.md).

---

## Button Removal (issue #93)

Card slots previously also rendered a Bench/Activate text button and ◀/▶ move-left/move-right
buttons (added for keyboard/non-drag-touch accessibility). Per issue #93, all four are removed
so drag-and-drop is the sole, uncluttered mouse-based way to move cards. To avoid leaving
keyboard-only users with no way to activate/bench a card, focusing a card image and pressing
Enter or Space now toggles it between bench and active instead of opening the card detail
modal. Since #186 the toggle (`toggleCardZone`) edits the local layout like a drop: a roster
card goes to the front of the bench, a bench card to the first free roster slot. Mouse click
still opens the detail modal, unchanged. In-zone reordering (the ◀/▶ buttons'
function) has no keyboard fallback after this change — it is drag-and-drop only, an explicit
accepted tradeoff, not an oversight.

---

## Drag Zones

The My Team tab has two drop zones:

- **Active grid** — up to 5 cards in fixed slots. Empty slots are rendered as placeholders,
  so gaps between cards are kept.
- **Bench** — all remaining cards, in order. No fixed slot count.

When the shown week is locked, cards can't be picked up and Enter/Space does nothing.

The grids get their pointer, click and key listeners once (`_bindRosterGrid`), and the
keyed render keeps each card's node (#159, #186); see `flicker-free-tab-switching.md`.

---

## Drag

Pointer Events replace HTML5 drag-and-drop (#186), so dragging also works on phones.

- **Pick up.** Mouse or pen: press on a card and move it more than 6 px. Touch: hold a card
  for 250 ms; moving before that scrolls the page as usual. A click or tap without movement
  opens the card viewer.
- **Follow.** The picked-up card lifts (`scale(1.04)`, shadow) and follows the pointer; its
  place in the grid stays as a dimmed gap. While a card is held the page doesn't scroll,
  except when the pointer is within 48 px of the viewport's top or bottom edge, where it
  auto-scrolls.
- **Live preview.** The slot under the pointer shows the result before the drop: in a zone
  the other cards slide aside (FLIP glide, about 220 ms). Over an occupied roster slot, a
  bench card shows a swap preview instead: the card it would replace dims, with an arrow to
  the bench. A move that breaks a rule is not previewed.
- **Highlights (#93).** For the whole drag both zones light up (`.drop-targets-active`:
  pulsing empty slots, dashed bench outline), and the card or empty slot under the pointer
  gets `.drag-over`.
- **Drop.** The move applies at once and the cards glide into place; the dropped card glides
  from where it was released. A refused move (full roster, a second card of the same player,
  a removed player) glides back and the status line names the rule.
- **Cancel.** Releasing outside both zones, pressing Escape or a cancelled pointer returns
  the card to its place with a glide; nothing is saved.
- **FLIP.** Every glide uses the shared `flipMove(els, first, opts)` in `app-globals.js`:
  `first` maps each node to its rect before the DOM change, then each moved node is inverted
  with a `transform` and played back (`FLIP_DURATION_MS` 220 ms, `opts.duration` to change
  it; #155's substitution playback passes 700 ms through `renderRosterLayout(layout,
  { animate: true, duration })`). Nothing glides under `prefers-reduced-motion`. The other My
  Team animations (count-ups, lock stamp, substitutions) are described in
  [Weekly Recap Animations](weekly-recap-animations.md#my-team-motion-issue-155).

| Drag from | Drop onto | Result |
|---|---|---|
| Active card | Active card | Moves to that position; the cards between slide aside |
| Active card | Empty active slot | Moves to that slot |
| Active card | Bench card | Benched, before that bench card |
| Active card | Bench background | Benched, last on the bench |
| Bench card | Bench card or background | Reorders the bench |
| Bench card | Empty active slot | Joins the roster in that slot |
| Bench card | Active grid background | Joins the roster in the nearest empty slot ("Roster full" when there is none) |
| Bench card | Populated active slot | Swap: the bench card takes the slot, the replaced card takes its place on the bench |

The layout is saved automatically 600 ms after the last move with one `PUT /roster`; see
[My Team Fluid Roster](my-team-save-roster.md#autosave).

---

## Data Model

**`cards.slot_index`** (new column, Integer, nullable):
Zero-based integer recording the card's preferred position within its current zone: the
roster slot for an active card, the bench position for a bench card. `PUT /roster` (#186)
sets both zones' positions in one write. `NULL` means unordered — cards sort after positioned
cards, then by `card.id`.

Migration: `021_card_slot_index` — `ALTER TABLE cards ADD COLUMN slot_index INTEGER`.

---

## Endpoints

### `GET /roster/{user_id}` *(modified)*
Active and bench lists are both returned sorted by `slot_index` (nulls last), then by
`card.id` as a tiebreaker.

### `PUT /roster` (#186)
Stores the whole layout (roster slots and bench order) with a version check. My Team uses it
for every change; see [My Team Fluid Roster](my-team-save-roster.md#endpoints).

The HTTP routes below stay for older clients. The Twitch panel has its own `/twitch/roster/...` routes, which reuse these routes' functions (`activate_card`, `deactivate_card`, `swap_roster`).

### `POST /roster/reorder`
Accepts `{"card_ids": [int, ...]}`. Sets `slot_index` to the list position for each card.
Used for in-zone reorder and for assigning a bench position after a zone transfer. Only
cards owned by the authenticated user are updated; unrecognised IDs are silently skipped.
`card_ids` may hold at most 500 items; a longer list returns 422 (issue #135).

### `POST /roster/swap`
Accepts `{"bench_card_id": int, "active_card_id": int, "slot_index": int}`. Atomically
deactivates the active card (clearing its `slot_index` to `NULL`) and activates the bench
card into the given slot. Applies the same duplicate-player guard as the existing activate
endpoint. Returns 404 if either card is not found or not in the expected zone; 409 if the
duplicate-player guard fires.

### `POST /roster/{card_id}/activate` and `POST /roster/{card_id}/deactivate` *(existing)*
Activate a bench card or bench an active card. Before #186 My Team used them for
bench→empty-slot and active→bench drags, followed by a reorder call.

---

## Backdrop Dismiss

Clicking the dark overlay surrounding the card viewer closes the modal (`e.target === modal`
guard, same pattern as draw result modal). Clicks inside the card content box are stopped by
`stopPropagation()` on the inner container.

