# My Team Fluid Roster

My Team edits the roster as a local layout: moves apply instantly and glide into place, dragging follows the pointer (also on touch) with a live preview, and the layout is saved automatically with one validated, versioned `PUT /roster`. Resolves GitHub issue #186, and takes over idea 2 of #155. Plan: `markdown/plans/plan-issue-186-my-team-save-roster.md`.

Code: `frontend/app-roster.js` (layout, render, drag, autosave), `frontend/app-globals.js` (`prefersReducedMotion()`, `flipMove()`), `backend/card_utils.py` (`roster_layout`, `layout_version`, `roster_version`, `apply_roster_layout`), `backend/routers/cards.py` (`save_roster` / `save_roster_route`). No schema change, no env var.

---

## Local layout and motion

The page keeps `_layout = {active, bench, version}`: `active` has one entry per roster slot (card id, or `null` for an empty slot, so gaps are kept), `bench` the bench ids in order, `version` the stored layout it is based on. `loadRoster()` builds it from `GET /roster/{user_id}` (a card sits in its `slot_index`; one without a usable slot takes the first free one).

`renderRosterLayout()` renders a layout keyed by card id: each card keeps its `.card-slot` node (`_rosterNodes`), empty slots keep theirs, and a render only reorders nodes (`replaceChildren`) and rewrites a card's inner markup when its points or labels changed. After a move nothing is fetched or redrawn.

`flipMove(els, firstRects, {from, duration})` (app-globals.js, shared with #155) plays each moved node from its old place to its new one: an inverted `translate`, then `transition: transform 220ms var(--ease-out)` (or `duration` ms; the #155 substitution playback uses 700). A dropped card starts where it was released (`from`). With `prefers-reduced-motion` it does nothing, so cards jump to their places; the roster's transitions and animations are also off in CSS.

**Rules**, checked locally before a move is shown (`_rosterRuleError`), with the status line naming the rule and the cards gliding back:

| Rule | Status line |
|---|---|
| At most 5 roster cards | `Roster full (5 cards max)` |
| One roster card per player | `A card for this player is already active` |
| No removed player on the roster (a card with `player_is_active: false`) | `A removed player can't be on the roster` |

`GET /roster` leaves out removed players' cards for the editable week, so the third rule only matters for a player removed while the page is open; the server checks all three again.

**Moves** (`_rosterMove`): a roster card dropped on another roster card takes its position and the cards between slide aside; on an empty slot it moves there; on the bench it goes before the bench card under it, or last. A bench card on a roster card swaps with it (the replaced card takes the bench card's place); on an empty slot, or the roster's background (its nearest empty slot), it joins the roster; on the bench it reorders the bench. Enter/Space on a focused card (`toggleCardZone`) uses the same path: a roster card goes to the front of the bench, a bench card to the first free slot.

## Pointer drag

Pointer Events on the two grids, bound once (`_bindRosterGrid`); see [My Team Drag-and-Drop](my-team-drag-and-drop.md#drag) for the interaction. A mouse or pen drag starts after 6 px of movement; a touch drag after a 250 ms hold (moving earlier lets the page scroll). The held card gets `touch-action: none`, and a non-passive `touchmove` listener stops the page from scrolling while a card is held. A copy of the card (`.roster-drag-clone`) follows the pointer; the card's own node stays as the dimmed gap (`.drag-placeholder`).

The target under the pointer (`document.elementFromPoint`, once per animation frame) is previewed from a copy of the layout (`_drag.preview`), so the other cards slide aside; `_layout` changes only on the drop. A bench card over a roster card marks that card `.swap-preview` (dimmed, with an arrow to the bench) instead. A move that breaks a rule isn't previewed and is refused on the drop. Near the top or bottom 48 px of the viewport the page scrolls. Escape, `pointercancel` or a release outside both grids cancels: the card glides back and nothing is saved.

## Autosave

States: `idle` → `waiting` (600 ms debounce from the last move) → `saving` → `idle`, plus `error`.

- **One save at a time.** A move during a save is applied locally and marks the layout dirty; one follow-up save sends the newest layout after the running one answers. Moves are never blocked.
- **Flush.** A waiting save goes at once on `visibilitychange` (hidden) and `pagehide` (with `fetch` `keepalive`), when the player leaves My Team (`switchTab` calls `flushRosterSave()`), changes week or presses Refresh (`loadRoster()` waits for the save first), and on every move once the shown week locks in under 2 minutes. There is no leave prompt.
- **Rate limit.** A long drag session can pass `RATE_LIMIT_ROSTER_MUTATION`. On a 429 the autosave waits for `Retry-After` (10 s without it) and sends the newest layout once more by itself, still showing "Saving…"; moves meanwhile don't send early saves. Only when that retry fails too does the status line say "Couldn't save.".
- **Status line** (`#rosterStatus`): "{n}/5 active" while idle or waiting; "Saving…"; "Saved" for 2 seconds; "Couldn't save." with a **Retry** button (`#rosterRetryBtn`) after a network error, a second 429 or another unexpected answer (the server's message is appended). The layout stays as arranged, and Retry or the next move sends it again.
- **Answers.** 200: the page adopts the new `version` (and the stored layout, with a glide, if it differs). 409 with `X-Roster-Conflict: version`: the page fetches the roster, glides the cards to it and shows "Your roster changed elsewhere. Showing the latest."; moves made since the refused save are dropped. Another 409, a 404 or a 422: the server's message, and the stored layout. When the answer's week starts after the shown one (the shown week locked meanwhile): "Week 5 locked; this change counts from Week 6".

## Endpoints

### `PUT /roster`
Logged in; `RATE_LIMIT_ROSTER_MUTATION` per user (`key_by_user_or_ip`). Card ids must be 1 to 2^63−1 (a larger one would overflow SQLite's integer bind; it answers 422). Body:

```json
{ "active": [42, null, 17], "bench": [8, 3], "base_version": "4cae17486dcce52c" }
```

`active`: at most `ROSTER_LIMIT` entries, `null` for an empty slot; `bench`: at most `ROSTER_BENCH_MAX` = 5000 ids (above any reachable collection, so a whole bench always fits); `base_version`: 1-64 characters. `apply_roster_layout` runs in one transaction:

1. A no-op `UPDATE users` takes SQLite's write lock, so of two saves from the same base the second waits and then sees the first one's version.
2. Checks, in order: `base_version` matches (409 with header `X-Roster-Conflict: version`); no id listed twice (409 "A card is listed more than once"); at most `ROSTER_LIMIT` slots (409 "Roster full (5 cards max)"); every card is the caller's (404 "Card not found", as the single-card routes answer); one roster card per player (409 "A card for this player is already active"); no removed player on the roster (409 "A removed player can't be on the roster").
3. A layout identical to the stored one writes nothing.
4. Every card not listed as active is benched (`is_active = 0`, `slot_index = NULL`) before any card is activated, so the partial unique index `ux_cards_owner_player_active` (#185) holds after each statement; then roster cards get `slot_index` = their slot and bench cards their position. An `IntegrityError` answers the duplicate-player 409.

The answer is the `GET /roster/{user_id}` response for the next editable week plus `version`. The live cards are the roster of the next editable week, so after a week's lock a save counts from the next week (as the single-card routes do), and `week` names it.

### `GET /roster/{user_id}`
Adds `version`: `roster_version()`, the first 16 hex characters of SHA-256 over `active:<ids>|bench:<ids>` for the stored layout (the cards of active players, as the page shows them). Roster ids are in slot order with `-` for an empty slot between cards (trailing empty slots left out); bench ids in order.

The single-card HTTP routes (`/roster/{id}/activate`, `/deactivate`, `/roster/swap`, `/roster/reorder`) stay for older clients. The Twitch panel has its own `/twitch/roster/...` routes, which reuse these routes' functions (`activate_card`, `deactivate_card`, `swap_roster`); they are unchanged.

## Tests

`backend/tests/test_issue_186_my_team_save_roster.py`: the backend checks and the concurrent-save race (file database, two threads), and a Node harness that runs `app-roster.js` against a fake DOM, timers and `fetch` for the drag, preview, rules, debounce, single flight, flushes and conflict handling.
