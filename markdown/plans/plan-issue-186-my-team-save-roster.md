# Plan: My Team Save Roster

> **Status: parked (2026-10-13).** Not scheduled. It is not yet clear that a Save step wouldn't degrade the My Team experience more than it helps (an extra step, unsaved-draft and lock-time risks, versus fewer writes). Revisit with player feedback before running `/develop`.

## Context
Every change on My Team is its own database write today: a drag inside a zone calls `POST /roster/reorder`, a bench-to-roster drag `POST /roster/swap`, and a click `POST /roster/{card_id}/activate` or `/deactivate` (`frontend/app-roster.js`). A player arranging their team sends a dozen writes for one decision.

Issue #186 proposes editing the roster in the browser and storing it with one **Save**. Its worry is a player who makes changes, doesn't save, and has the week lock on a roster they didn't mean.

**Cost and benefit, honestly:** each single write is cheap (one small `UPDATE`, limited per user by `RATE_LIMIT_ROSTER_MUTATION` since #124 and made atomic by #185). The gains are mostly elsewhere:
- one validated, atomic write per decision;
- no half-applied rosters between drags;
- fewer requests;
- a deliberate "this is my team" moment.

**The risks** are unsaved drafts and a draft that goes stale because the roster changed in another tab or the Twitch panel. The plan handles both:
- **Visibility:** a visible unsaved-changes bar.
- **Leaving:** a prompt when leaving My Team or the page.
- **Lock time:** a warning before the week locks.
- **Reloads:** a draft kept across reloads.
- **Stale drafts:** a version check that refuses to overwrite a roster changed elsewhere.

The single-card routes stay: the Twitch panel and older clients use them.

Assumption: the Twitch panel keeps its immediate per-action roster changes. A save step suits a full-size page better than a 318 px panel.

Resolves GitHub issue #186.

## User Stories

### Arrange the Roster, Then Save Once
**User story**
As a player, I want to drag cards between roster and bench and reorder them freely, then save the result once so that my team is stored as one decision.

**Acceptance criteria**
- On My Team for the current (unlocked) week, activate, deactivate, swap and reorder change only the page's draft; no roster request is sent until **Save**
- **Save** sends `PUT /roster` with the whole layout: `{"active": [card ids in slot order], "bench": [card ids in bench order], "base_version": "<version>"}`
- The server applies it in one transaction, or not at all, and checks:
  - every card belongs to the user;
  - each card appears exactly once;
  - at most `ROSTER_LIMIT` cards are active;
  - no two active cards have the same player;
  - no inactive (removed) player is active.
- A failed check answers 409 or 422 with a message naming the problem; nothing changes
- On success the server answers with the saved roster and its new `version`, and the page shows "Roster saved"
- Saving an unchanged draft is a no-op that still answers 200
- `PUT /roster` has the per-user `RATE_LIMIT_ROSTER_MUTATION` limit
- The existing single-card routes keep working unchanged

### See Unsaved Changes at a Glance
**User story**
As a player, I want an obvious sign that my roster has unsaved changes so that I never think a change is stored when it isn't.

**Acceptance criteria**
- While the draft differs from the saved roster, a bar shows "Unsaved changes" with **Save** and **Discard**; it is hidden when they match
- Changed cards are marked in the draft, by an outline or a "moved" badge
- **Discard** restores the saved roster without a request
- **Save** is disabled while its request runs (the #185 in-flight guard) and while the draft breaks a rule the page can check, for example more than `ROSTER_LIMIT` active cards; the reason is shown next to it

### Don't Lose Changes by Leaving
**User story**
As a player, I want to be asked before I leave My Team with unsaved changes so that I can save them first.

**Acceptance criteria**
- With unsaved changes, switching to another tab, choosing another week, logging out or opening the Weekly Report shows a prompt: **Save and continue**, **Discard and continue**, **Stay**
- Closing or reloading the page triggers the browser's own leave-page warning (`beforeunload`); the page can't customise its text
- The draft is kept in `sessionStorage`. After a reload in the same tab, My Team offers "You have unsaved roster changes. Restore / Discard" when the saved roster's version still matches the draft's `base_version`; otherwise the draft is dropped and a note says the roster changed meanwhile
- No prompt appears when there are no unsaved changes

### Don't Lock a Roster You Didn't Mean
**User story**
As a player, I want a warning before the week locks while I have unsaved changes so that my intended roster is the one that counts.

**Acceptance criteria**
- With unsaved changes, the unsaved-changes bar shows the time to lock once the week's `start_time` is within `ROSTER_SAVE_WARNING_MINUTES` (default 30)
- If the week locks while the draft is unsaved, the draft is not applied. The page says "The week locked before your changes were saved. Your saved roster was used." and keeps the draft for the next week if it is still valid
- `PUT /roster` for a week whose lock has passed changes the cards for the next week, matching how the single-card routes behave today; the response says which week the roster now counts for

### A Roster Changed Elsewhere Isn't Overwritten
**User story**
As a player using two tabs or the Twitch panel, I want saving an old draft to fail rather than silently undo changes I made elsewhere.

**Acceptance criteria**
- `GET /roster/{user_id}` for the current week returns a `version`: a hash of the user's active card ids in slot order and bench card ids in order
- `PUT /roster` recomputes the version inside the transaction and answers 409 "Your roster changed since you started editing. Reload to see it." when `base_version` doesn't match; nothing changes
- After a 409 the page offers **Reload roster**, which discards the draft

## Implementation

### Critical Files
| File | Change |
|---|---|
| `backend/routers/cards.py` | `PUT /roster` (`save_roster` + `save_roster_route`), `version` in the roster response |
| `backend/card_utils.py` | `roster_version(db, user_id)`; `apply_roster_layout(db, user_id, active, bench, base_version)` doing the checks and writes in one transaction |
| `frontend/app-roster.js` | Draft state: drag-and-drop and clicks edit the draft; Save / Discard bar; dirty marks; `sessionStorage` draft; 409 handling |
| `frontend/app-globals.js` | Leave guard: `switchTab` and the week selector ask `confirmLeaveRoster()`; `beforeunload` while dirty |
| `frontend/app-auth.js` | Logout goes through the leave guard |
| `frontend/index.html` | Unsaved-changes bar markup; leave prompt dialog |
| `frontend/style.css` | Bar and changed-card styles |
| `.env.example` | `ROSTER_SAVE_WARNING_MINUTES` (passed to the page through `GET /config`) |
| `backend/main.py` / config route | Expose `roster_save_warning_minutes` in `/config` |
| `markdown/features/core/cards.md`, `markdown/ui_description/my-team.md`, `markdown/features/reference/my-team-drag-and-drop.md` | Docs |
| `backend/tests/test_issue_186_my_team_save_roster.py` | Tests |

No schema change.

### Step 1 — Version and layout apply
- `roster_version` hashes `active:<id,id,…>|bench:<id,…>` (SHA-256, first 16 hex characters), in the same order the page shows.
- `apply_roster_layout`:
  1. Starts with a write (or `BEGIN IMMEDIATE`) so the version check and the writes see one state. SQLite runs one writer at a time, as in #185.
  2. Compares the version, and validates ownership, duplicates, `ROSTER_LIMIT`, unique active players and active players.
  3. Benches every card not in `active`, with `slot_index = NULL`, then sets `is_active = 1` and `slot_index` for the active list, then bench `slot_index` values in order.

  Deactivating first keeps the #185 partial unique index (`ux_cards_owner_player_active`) happy. Any `IntegrityError` still becomes 409.

### Step 2 — Route
```python
class SaveRosterBody(BaseModel):
    active: list[int] = Field(max_length=ROSTER_LIMIT)
    bench: list[int] = Field(max_length=500)
    base_version: str = Field(min_length=1, max_length=64)
```
`PUT /roster` uses `get_current_user`, `RATE_LIMIT_ROSTER_MUTATION` keyed by user, and returns `_build_roster_response` plus `version`. Follow the route-wrapper pattern (`*_route` with `request: Request`). The #184 route-coverage test then sees the limit.

### Step 3 — Frontend draft
`app-roster.js` keeps `_rosterSaved` (from the server) and `_rosterDraft` (a working copy). The drop and click handlers that call the four routes today edit `_rosterDraft` and re-render. The `_rosterBusy` guard (#185) covers only Save.
- **Dirty check:** compare the draft's active and bench lists with the saved ones.
- **Draft storage:** keep the draft in `sessionStorage` under `rosterDraft:<userId>` with its `base_version`.
- **Save:** `withBusy(saveBtn, …)` sends `PUT /roster`. On 200 the response becomes the saved roster and the draft is cleared. On 409 or 422 the page shows the message, and on a version mismatch it offers **Reload roster**.

### Step 4 — Leave guard
- **In-app navigation:** `switchTab(name)`, the week selector, logout and the Weekly Report button call `confirmLeaveRoster()` when the draft is dirty. It resolves after Save, Discard or Stay; Stay cancels the navigation.
- **Page unload:** `window.addEventListener("beforeunload", …)` is set only while the draft is dirty.

### Step 5 — Lock warning
`GET /config` adds `roster_save_warning_minutes`. The bar shows "Locks in N min" once the selected week's `start_time` is within that window. When a roster reload shows the week locked, any unsaved draft is reported as not applied, then kept or dropped as the story says.

### Step 6 — Tests
`backend/tests/test_issue_186_my_team_save_roster.py`:
- **Backend:**
  - `PUT /roster` applies a valid layout in one transaction;
  - each validation failure leaves the roster unchanged;
  - version mismatch gives 409;
  - an unchanged draft is a no-op;
  - another user's card is refused;
  - rate limit;
  - the response's `version` matches `GET /roster`;
  - concurrent saves with the same base version: one wins and the other gets 409 (file-based SQLite and `threading.Barrier`, as in #185).
- **Static frontend checks:**
  - the handlers no longer call the single-card routes on My Team;
  - the Save / Discard bar;
  - the `beforeunload` registration;
  - the `confirmLeaveRoster` calls in `switchTab`, the week selector and logout;
  - the `sessionStorage` draft.

Keep `test_issue_85`'s suite-size baseline and the #184 route-coverage test in step.

### Step 7 — Docs
- **`my-team.md`:** draft editing, the unsaved bar, the leave prompt, the lock warning.
- **`my-team-drag-and-drop.md`:** drops edit the draft.
- **`cards.md`:** the `PUT /roster` endpoint.
- **Configuration:** `ROSTER_SAVE_WARNING_MINUTES`.

## Verification
- **Draft and save:**
  1. Drag a bench card onto the roster, reorder two slots and bench one card. The network shows no roster requests, and the bar shows "Unsaved changes".
  2. Save: one `PUT /roster`, "Roster saved", and the bar disappears. Reloading shows the saved layout.
- **Leaving with unsaved changes:**
  - switching tabs prompts, and Stay keeps you on My Team;
  - closing the tab shows the browser's warning;
  - reloading offers Restore.
- **Two tabs:** save in tab A, then save an older draft in tab B: tab B gets the "changed since you started editing" message, and nothing is overwritten.
- **Lock warning:** with `ROSTER_SAVE_WARNING_MINUTES` large, or the demo clock near a lock, the bar shows the countdown.
- **Twitch panel:** roster actions still apply immediately.
- **Tests:** `cd backend && python3 -m pytest tests/ -q`.
