# Plan: Fix Available Draws Count Display

## Context
GitHub issue #89 reports that the "X draws available" status line on the Draw panel shows an
absurdly large number (300+) instead of the user's real remaining draw count, and that when
draws are actually exhausted the user gets a 409 error rather than the UI having already shown
0 available. A follow-up comment notes the bug "does not appear in Prod" — this plan resolves
that apparent contradiction with a concrete root cause rather than treating it as unreproducible.

Root cause, confirmed by reading the code directly: `loadDeck()` in `frontend/app-cards.js:358-377`
fetches `GET /deck` and sums its four per-rarity values into a `total`, which it displays as
"{total} draws available". Per `GET /deck`'s actual documented behavior
(`markdown/features/core/cards.md` "Card Endpoints"), that response is the count of distinct
`(player, rarity)` combinations the user has **not yet drawn** — not a draw allowance. Since
`POST /draw` costs a flat 1 token and (per `reference/dynamic-card-creation.md`) is never
actually blocked by combo exhaustion — the uniqueness constraint relaxes once every combo is
owned — the true number of draws a user can make is simply their **token balance**, which is
already computed correctly and displayed correctly by the adjacent `#drawCounter` element via
`updateTokenDisplay()`. The two elements sit right next to each other showing two different,
disagreeing numbers, and only the second one (`#deckStatus`) is wrong.

This also explains the "not in Prod" observation: the sum is large and obviously wrong for an
account with few owned cards (many undrawn combos across ~76+ players × 4 rarities), but for a
long-running Prod account that already owns most players, the same broken calculation happens to
land on a smaller, less conspicuously-wrong number. The defect is present in both environments;
only its visibility differs by account data state.

Because `markdown/features/reference/draw-panel-redesign.md` already documents `loadDeck()` and
this exact status line in detail, this plan **updates that file in place** rather than creating a
duplicate stub, per the project's "do not duplicate documentation" rule.

Resolves GitHub issue #89.

## User Stories

### Accurate Available Draws Count
**User story**
As a user, I want the "draws available" number on the Draw panel to reflect my actual remaining
draws (my token balance) so that I am not misled into thinking I can draw far more cards than I
actually can.

**Acceptance criteria**
- The Draw panel's `#deckStatus` line shows a number derived from the user's current token
  balance, not from `GET /deck`'s summed per-rarity undrawn-combination counts
- Immediately after a successful standard or team-booster draw, the number decreases by 1 to
  match the new token balance returned by the draw response, with no page refresh needed
- When the user has 0 tokens, the line shows "No draws available", matching the account's actual
  draw eligibility (`POST /draw` returns 409 at this point)
- Logged-out users are not shown a specific draws-available number derived from data that
  doesn't apply to them, mirroring the existing logged-out behavior of `#drawCounter`

### Consistent Draw-Count Messaging
**User story**
As a user, I want the two draw-count indicators near the Draw button (the counter beside the
button and the status line below it) to always agree with each other so that I am not shown two
different numbers for the same thing.

**Acceptance criteria**
- `#drawCounter` and `#deckStatus`'s "draws available" text derive from the same source of truth
  (the user's token balance, `_tokenBalance`)
- After a successful draw (standard or team-booster), both indicators update together in the
  same call, so they can never show conflicting numbers even momentarily
- `GET /deck`'s response shape, and its use by the team-booster panel (`GET /deck/booster`,
  `loadBoosterTeams()`), are unaffected — this fix only changes how `loadDeck()`'s status line
  interprets data, not the `/deck` endpoint's contract or any other caller of it

## Implementation

### Critical Files
| File | Change |
|---|---|
| `frontend/app-cards.js` | `loadDeck()` (lines 358-377): stop summing `GET /deck`'s per-rarity counts for the status line; derive the "draws available" text from `_tokenBalance` instead. Remove the now-unused `GET /deck` fetch from this function (nothing else in `loadDeck()` consumes it — the per-rarity `deck-{rarity}` elements are already populated from `GET /config`'s `draw_rates`, per the prior Draw Panel Redesign plan) |
| `markdown/features/reference/draw-panel-redesign.md` | Update the "Frontend change" and "Implementation notes" sections to describe the corrected status-line source and the removed `/deck` fetch |
| `markdown/stories/cards.md` | Append the two stories above |

### Step 1 — Fix `loadDeck()`
Replace the summed-total logic with the token balance already tracked globally:

```js
async function loadDeck() {
  try {
    const cfg = await (await fetch(`${API}/config`)).json();
    const rates = cfg.draw_rates || { common: 60, rare: 25, epic: 10, legendary: 5 };
    for (const r of DRAW_RARITY_KEYS) {
      document.getElementById(`deck-${r}`).textContent = `${rates[r]}%`;
    }

    const total = _tokenBalance ?? 0;
    setStatus("deckStatus", activeUserId && total > 0 ? `${total} draws available` : "No draws available");
  } catch (e) {
    setStatus("deckStatus", e.message, false);
  }
}
```

`_tokenBalance` (`frontend/app-globals.js:8`) is guaranteed populated before `loadDeck()` runs at
every call site — `loadMe()` (called from `init()`, `login()`, `register()`) and every draw
handler (`drawCard()`, `_drawBoosterForTeam()`) call `updateTokenDisplay()` synchronously before
`loadDeck()` — so no new fetch or race condition is introduced.

### Step 2 — Documentation
Update `markdown/features/reference/draw-panel-redesign.md`'s "Frontend change" and
"Implementation notes" sections: replace the statement that `/deck` drives the status line draw
count with the corrected description (status line now derived from token balance; `/deck` is no
longer fetched by `loadDeck()`). Append the two stories to `markdown/stories/cards.md` under a
new `## Fix Available Draws Count Display` heading (after the existing `## Draw Panel Redesign`
section). Note: that existing section's "View Drop Percentages in the Draw Panel" story has an
acceptance criterion stating "The 'X draws available' status line ... [is] unchanged" — this was
accurate for that earlier plan's scope but is now stale; add a one-line note to that AC (not a
rewrite) pointing to this plan, consistent with how prior superseded-AC notes have been handled
in this file elsewhere.

## Verification
- Log in as an account with many undrawn `(player, rarity)` combinations (e.g. a fresh account);
  confirm the Draw panel shows a number equal to the account's actual token balance, not a
  triple-digit combination sum
- Perform a successful draw; confirm the number decrements by 1 immediately, matching the token
  count in the draw response, and stays in sync with `#drawCounter`
- Deplete tokens to 0; confirm the line reads "No draws available" and `POST /draw` correctly
  returns 409 "Not enough tokens" — no more disagreement between a large displayed count and an
  immediate real-world failure
- Confirm the team-booster panel (`GET /deck/booster`, `loadBoosterTeams()`) is unaffected — it
  does not use `loadDeck()`'s total
- No backend change, no migration — this is a frontend-only fix
