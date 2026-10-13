# My Team Save Roster

On My Team, roster changes (activate, bench, swap, reorder) edit a draft in the page and are stored with one **Save**, in one validated transaction. Unsaved changes are always visible, leaving prompts to save, a warning shows before the week locks, and a roster changed elsewhere is never overwritten. Resolves GitHub issue #186. **Parked:** not scheduled; see the plan's status note.

---

## Draft and save *(planned)*

The page keeps the saved roster and a working draft. Drag-and-drop and clicks change only the draft. **Save** sends the whole layout; **Discard** restores the saved roster. The draft survives a reload in the same tab (`sessionStorage`) while the saved roster's version still matches.

## Leaving with unsaved changes *(planned)*

Switching tab, choosing another week, logging out or opening the Weekly Report asks **Save and continue** / **Discard and continue** / **Stay**. Closing or reloading the page shows the browser's leave-page warning.

## Week lock *(planned)*

With unsaved changes, the bar shows the time left before the week locks once it is within `ROSTER_SAVE_WARNING_MINUTES`. A draft not saved before the lock is not applied, and the page says so.

## Endpoints

### `PUT /roster` *(planned)*
Logged in; `RATE_LIMIT_ROSTER_MUTATION` per user. Body: `{"active": [card ids in slot order], "bench": [card ids in order], "base_version": "…"}`.

It checks, in one transaction:
- the cards are the user's own;
- no card is listed twice;
- at most `ROSTER_LIMIT` cards are active;
- no two active cards have the same player;
- no active card is of a removed player;
- the roster still has `base_version`.

It answers with the saved roster and its new `version`; 409 on a version mismatch or a rule conflict, 422 on an invalid body. Nothing changes on failure.

### `GET /roster/{user_id}` *(planned change)*
Adds `version` for the current week: a hash of the active and bench card ids in order.

The single-card routes (`/roster/{card_id}/activate`, `/deactivate`, `/roster/swap`, `/roster/reorder`) are unchanged; the Twitch panel keeps using them.

## Configuration

| Variable | Default | Description |
|---|---|---|
| `ROSTER_SAVE_WARNING_MINUTES` | `30` | Minutes before the week locks from which unsaved roster changes show a lock countdown |

---

*This document is a stub created at feature planning time. Fill in implementation details once the feature is built.*
