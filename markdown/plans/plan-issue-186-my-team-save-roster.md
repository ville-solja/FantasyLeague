# Plan: My Team Fluid Roster (local edits, autosaved layout)

> **Status: revised (2026-10-14).** The parked version proposed an explicit **Save** step. This version keeps that plan's backend (one validated, versioned `PUT /roster`) but saves automatically, so there is no Save button, unsaved-draft prompt or lock-time warning. It now also carries the drag-and-drop motion proposed in #155 (idea 2). The earlier Save-button design is replaced, not kept.

## Context
**Why a roster move on My Team jumps today** (`frontend/app-roster.js`):
1. **Static drag image.** Dragging uses HTML5 drag-and-drop. The browser's drag image is a static snapshot, and the other cards can't make room while you drag.
2. **Wait with no feedback.** On drop, the page waits for one to three requests: a swap is one call; a move to the bench is `deactivate` plus `reorder`. During that wait nothing changes on screen, and a second drop is ignored (`_rosterBusy`).
3. **Full redraw.** Then `loadRoster()` re-fetches and redraws both grids, so every card appears in its new place at once. The 180 ms `card-settle` only scales cards in place; it doesn't show where they came from.
4. **No phone dragging.** HTML5 drag-and-drop doesn't work on phones. On touch devices the roster can only be changed by the keyboard toggle path, and there is no in-zone reordering at all.

#186 proposed editing a local draft and storing it with one write. Its backend part is what makes a fluid editor possible: if the page owns the layout and only stores it, every move can be instant and animated. What made #186 risky was the explicit Save step. Saving the layout automatically, about half a second after the last move, keeps the fluid editing and drops that risk.

**The result:**
- **Instant moves:** cards follow the pointer, the roster makes room live, and a drop lands with a short glide (FLIP) with no network wait.
- **Touch drag:** dragging works on phones (long-press to pick up).
- **One save per burst:** each burst of moves becomes one atomic, validated `PUT /roster` with a version check, so no half-applied rosters.
- **Conflicts:** a change made elsewhere (another tab, the Twitch panel) is never overwritten. The page shows the latest roster with a short animation and a message.

**The single-card routes stay** for the Twitch panel and older clients: `/roster/{id}/activate`, `/deactivate`, `/roster/swap`, `/roster/reorder`.

Assumptions:
- **Debounce:** 600 ms after the last move, flushed at once when the page is hidden, the tab changes, or the week is under 2 minutes from locking.
- **Twitch panel:** unchanged.
- **Reduced motion:** moves still apply instantly, but nothing glides.

Resolves GitHub issue #186. Takes over idea 2 (bench ↔ roster slide) of #155.

## User Stories

### Moves Apply Instantly and Glide Into Place
**User story**
As a player, I want a card I drop to land in its new place right away, so that arranging my team feels direct instead of waiting for a reload.

**Acceptance criteria**
- **Local first:** dropping a card (reorder within a zone, bench → roster, roster → bench, swap) changes the page's layout at once, with no network wait.
- **Glide:** the dropped card glides from where it was released to its slot, and every card that changes position glides from its old place (FLIP, about 220 ms, `--ease-out`).
- **No refetch:** the page doesn't re-fetch or redraw the roster after a move. It renders from its local layout, keyed by card id, so the DOM nodes move rather than being rebuilt.
- **Rules checked locally:** a move that would break a rule is refused locally with the cards gliding back:
  - more than `ROSTER_LIMIT` active cards;
  - two active cards of the same player;
  - an inactive (removed) player on the roster.
  The status line names the rule.
- **Keyboard and touch:** the keyboard toggle (Enter/Space on a focused card) and tapping go through the same local layout and animation.
- **Reduced motion:** cards jump to their places with no glide.

### Drag Follows the Pointer and the Roster Makes Room
**User story**
As a player on desktop or phone, I want the card to follow my finger or mouse and the other cards to make room while I drag, so that I can see where it will land before I let go.

**Acceptance criteria**
- **Pointer drag:** dragging uses Pointer Events instead of HTML5 drag-and-drop. The picked-up card lifts (scale 1.04, shadow) and follows the pointer.
- **Live preview:** the slot under the pointer previews the result. In a zone, the other cards slide aside; over an occupied roster slot, a swap preview shows the replaced card dimmed with an arrow to the bench.
- **Touch:**
  - a press of 250 ms picks a card up;
  - moving before that scrolls the page as usual;
  - the page doesn't scroll while a card is held, except near the top or bottom edge, where it auto-scrolls.
- **Cancel:** releasing outside any zone, pressing Escape, or a cancelled pointer returns the card to its place with a glide.
- **Unchanged behaviour:** the existing drop-zone highlights (#93) stay, and a click without movement still opens the card viewer.
- **Locked weeks:** cards can't be picked up, as today.

### The Layout Saves Itself
**User story**
As a player, I want my roster stored without pressing anything, so that I can't forget to save before the week locks.

**Acceptance criteria**
- **Debounced save:** 600 ms after the last move, the page sends `PUT /roster` with the whole layout and the version it is based on:
  `{"active": [card ids in slot order], "bench": [card ids in order], "base_version": "…"}`
- **One save at a time:** a move during a save is applied locally, and the next save sends the newest layout. Saves never overlap, and moves are never blocked, so `_rosterBusy` no longer ignores drops.
- **Status line:**
  - "Saving…" while a save runs;
  - "Saved" for 2 seconds after it succeeds;
  - "Couldn't save. Retry" on a network error, with a Retry button. The layout stays as the player arranged it.
- **Flush instead of waiting:** when the page becomes hidden (`visibilitychange`/`pagehide`, with a `fetch` `keepalive` request), when the player switches tab or week, or when the selected week locks in under 2 minutes. Leaving My Team shows no prompt.
- **Rate limit:** `PUT /roster` has the per-user `RATE_LIMIT_ROSTER_MUTATION` limit. A burst of moves sends one save, not one per move.

### Saves Are Atomic and Never Overwrite Changes Made Elsewhere
**User story**
As a player using two tabs or the Twitch panel, I want a stale page not to undo changes I made elsewhere, so that my latest roster is the one that counts.

**Acceptance criteria**
- **Version on read:** `GET /roster/{user_id}` returns `version` for the current week: a hash of the active card ids in slot order and the bench card ids in order.
- **Checks:** `PUT /roster` checks in one transaction:
  - the cards are the user's own;
  - no card is listed twice;
  - at most `ROSTER_LIMIT` are active;
  - there are no two active cards of the same player;
  - no removed player is active;
  - `base_version` still matches.
- **Write:** it then benches every card not in `active` and sets the active slots and the bench order. It answers with the saved roster and its new `version`.
- **Failures:** a failed check answers 409 (version or rule) or 422 (bad body), and nothing changes.
- **On a version mismatch** the page:
  1. fetches the roster;
  2. animates the cards to the server's layout;
  3. shows "Your roster changed elsewhere. Showing the latest."
  Moves made after the failed save are dropped.
- **Unchanged layout:** saving a layout identical to the stored one is a no-op that still answers 200.
- **Week lock:** a save for a week whose lock has passed applies to the next week, as the single-card routes do today. The response names the week, and the page says "Week N locked; this change counts from Week N+1" when they differ.

## Implementation

### Critical Files
| File | Change |
|---|---|
| `backend/card_utils.py` | `roster_version(db, user_id)`; `apply_roster_layout(db, user_id, active, bench, base_version)`: checks and writes in one transaction. Benches first, so the one-active-per-player index (#185) holds |
| `backend/routers/cards.py` | `PUT /roster` (`save_roster` + `save_roster_route`, rate-limited); `version` on the roster response |
| `frontend/app-roster.js` | Local layout model (`_layout = {active, bench, version}`); keyed render (reuse nodes by card id); FLIP helper; Pointer Events drag controller (lift, follow, live preview, edge auto-scroll, long-press on touch, cancel); local rule checks; autosave queue (debounce, single flight, flush triggers, retry, conflict reload); keyboard toggle through the same path; HTML5 `draggable` handlers removed |
| `frontend/app-globals.js` | Shared `prefersReducedMotion()` and `flipMove()` (shared with #155) |
| `frontend/style.css` | Lifted card, live gap, swap preview, save status; transitions off under reduced motion (before the GUIDED TOUR section) |
| `markdown/features/reference/my-team-drag-and-drop.md`, `markdown/features/reference/my-team-save-roster.md`, `markdown/ui_description/my-team.md`, `markdown/features/core/cards.md` | Existing docs |
| `backend/tests/test_issue_186_my_team_save_roster.py` | Tests |

No schema change and no env var.

### Step 1 — Backend: version and layout save
- **`roster_version`:** hashes `active:<ids>|bench:<ids>` (SHA-256, first 16 hex characters).
- **`apply_roster_layout`:**
  1. take the write lock first (a no-op `UPDATE`, the pattern from #193);
  2. compare the version and run the checks;
  3. bench every card not listed active (`slot_index = NULL`), then set the active cards and their slots, then the bench order.

  Any `IntegrityError` becomes 409.
- **The route:**
  - follows the `*_route` wrapper pattern;
  - Pydantic body `active: list[int] = Field(max_length=ROSTER_LIMIT)`, `bench: list[int] = Field(max_length=500)`, `base_version: str = Field(min_length=1, max_length=64)`;
  - the #184 route-coverage test then sees the rate limit.

### Step 2 — Local layout and keyed render
- **Data:** `loadRoster` keeps the server layout as `_layout`, and moves edit `_layout`.
- **Rendering:** `renderRosterLayout()` reuses existing slot nodes by `data-card-id` and moves them in the DOM. Empty slots stay as placeholders, with the `slot_index` gaps kept.
- **Animation:** `flipMove()` records positions before the change and plays the inverse transforms after it.

### Step 3 — Pointer drag
- **The controller:** `pointerdown` on a card starts a pending drag. Movement over 6 px (mouse) or a 250 ms hold (touch) starts it; `pointermove` moves a fixed-position clone; `pointerup` drops it.
- **The target:** found from `document.elementFromPoint`.
- **Live preview:** reordering `_layout` in a preview copy, rendered with FLIP on every target change (throttled to animation frames).
- **Touch scrolling:** `touch-action: none` only on held cards, so page scrolling still works.

### Step 4 — Autosave queue
- **States:** `idle` → `waiting` (debounce) → `saving` → `idle`, plus `error`.
- **Single flight:** a move during `saving` marks the layout dirty, so a new save follows.
- **Flush:** on page hide, tab or week change, and within 2 minutes of the lock.
- **Responses:**
  - 200: adopt the version (and the layout, if it differs, with FLIP);
  - 409 version: the conflict reload;
  - 409 rule or 422: show the message and reload the server layout.

### Step 5 — Docs and tests
**Docs:** rewrite the drag section of `my-team-drag-and-drop.md` (Pointer Events, live preview, touch), fill in `my-team-save-roster.md` (autosave, conflicts), and add the save status and motion to `ui_description/my-team.md`.

**Tests:**
- **Backend:**
  - layout apply, each refusal, version mismatch, no-op, another user's card, rate limit;
  - the response's version matches `GET`;
  - concurrent saves from the same base: one wins and the other gets 409;
  - a locked week applies to the next week.
- **Frontend, Node harness:**
  - local rule checks;
  - the debounce collapses a burst into one `PUT`;
  - single flight sends the newest layout;
  - flush on `visibilitychange`;
  - a conflict reloads and drops later moves;
  - no `loadRoster()` refetch after a move.
- **Static checks:**
  - no HTML5 `draggable` handlers left;
  - transitions off under reduced motion.

## Verification
- **Desktop:**
  1. Drag a bench card over the roster: cards make room and the swap preview shows. Drop: it glides in, with no wait.
  2. Make five moves quickly: the network shows one `PUT /roster`, then "Saved".
  3. Reload: the layout is the same.
- **Phone:** long-press a card, drag it to the bench and drop; the page still scrolls normally without a long-press.
- **Two tabs:** move a card in tab A, then move one in tab B. Tab B shows "Your roster changed elsewhere", animates to A's layout, and nothing is overwritten.
- **Offline:** go offline and move a card. "Couldn't save. Retry" appears; back online, Retry saves it.
- **Lock:** with the demo clock near a lock, a move saves at once with no 600 ms wait.
- **Reduced motion:** moves apply with no glide.
- **Twitch panel:** roster actions still work as before.
- **Tests:** `cd backend && python -m pytest tests/test_issue_186_my_team_save_roster.py -q`, then `python -m pytest tests/ -n auto -q`.

## Implementation notes (2026-10-14)
- **Empty slots:** `active` in `PUT /roster` has one entry per roster slot, with `null` for an empty slot, so gaps between roster cards are kept (`list[int | None]`). The version string writes an empty slot as `-` and leaves out trailing empty slots.
- **Another user's card:** 404 "Card not found", the code the single-card routes use; the page treats it like a rule refusal (message, then the stored layout).
- **Version conflict signal:** a 409 for a stale `base_version` carries the header `X-Roster-Conflict: version`; rule refusals don't.
- **Unlisted cards:** every card not listed as active is benched with `slot_index = NULL`; listed bench cards then get their order.
- **Tapping:** a tap without movement still opens the card viewer (unchanged behaviour); touch drags and Enter/Space go through the local layout.
- **Other failures:** a 429 or other unexpected answer is handled like a network error ("Couldn't save." plus the server's message, Retry).
