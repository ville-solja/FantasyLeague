# My Team tab

Visible only to logged-in users.

## Layout

On desktop (≥ 768 px) the tab uses a two-column grid: **My Roster** occupies the main column (`1fr`) on the left and **Draw** occupies a fixed 300 px sidebar on the right. On narrow viewports (< 768 px) the columns collapse to a single stack — Roster first, Draw sidebar below.

## Draw panel

The panel starts with the **deck** (`#drawDeck`, decorative, `aria-hidden`): three stacked card backs in the brand pattern with a diamond emblem, CSS only, no league name. Beside it, under a **Chance per draw** caption, a compact two-by-two strip (`.rarity-grid`) shows the drop percentage of each rarity: a dot in the rarity colour, the name (Common, Rare, Epic, Legendary) and a normalised percentage (e.g. 60%, 25%, 10%, 5%) in `#deck-common`, `#deck-rare`, `#deck-epic`, `#deck-legendary`. Percentages come from `GET /config` → `draw_rates` (the live `draw_rate_*` scoring weights) and always sum to 100%. Below the deck and strip:

- **Draw a card** button — spends 1 token and draws a random card (#205). The deck picture (a stack of card backs, not the `GET /deck` counts) stirs while the draw answers and the card PNG loads and decodes (3 seconds at most). Then the deck's top card lifts (220 ms), flies to the centre while the page dims (460 ms) and flips face up with a slight overshoot and the rarity-coloured burst (520 ms); the rarity label, destination ("Added to active roster" / "Added to bench"), Reroll and Continue fade in (400 ms). If the image isn't ready after 3 seconds the card flips to its rarity face and the PNG appears when it loads; an image error shows the rarity name. A failed draw plays nothing and shows the error. **Continue** sends the card to where it was added — its roster slot or the front of the bench — (520 ms), where it glows once in its rarity colour (1.2 s). **Draw another card** starts the next draw from the deck; ✕, Escape and the backdrop close without the landing. **`prefers-reduced-motion`**: no stir, flight, flip, burst or landing flight; the finished reveal fades in, and the card shows a still rarity ring in its slot. **Rolled stat modifiers** are painted on the card image (lower band). Reroll: decode handoff + brief brightness flash on the image only. Details: `markdown/features/reference/card-draw-animations.md`.
- **Draw from a team (N Tokens)** button (`#boosterBtn`) — next to the standard draw. N is the live `team_booster_cost` from `GET /config` (fallback 3) and the token name comes from config. Disabled with a tooltip when logged out or when the balance is below N. Opens the team picker.
- **Draw hint** (`#boosterHint`) — a muted line under the buttons: "1 token for a random player, or N for a player from a team you pick. You get players you don't own yet first." N (`#boosterHintCost`) is filled from `team_booster_cost` in `GET /config`.
- **Team picker** (`#boosterModal`, titled "Choose a team") — a cost line "Costs N Tokens for 1 card", a grid of team tiles showing how many unowned players are left (fully collected teams are greyed out and read "Complete"), and Cancel / **Draw 1 card from this team** buttons. The confirm button is enabled once a team is selected; each opening starts with no team selected. "Loading…" shows only the first time the picker opens; later the tiles stay while the list refreshes, and a refresh error goes to the picker's status line (`#boosterStatus`). The picker closes as soon as the team draw answers, and the card flies from the deck as for **Draw a card**. After a team draw, the reveal modal's "Draw another card" repeats a team draw from the same team.
- **Draw reveal copy** — player and team names are **only on the card PNG** (not duplicated under the image), so layout tweaks in the generator (`_PLAYER_NAME_Y`, `_TEAM_NAME_Y`) match what you see. Opening a card from the roster without draw animation still shows name and team under the art. The Tags section shows under the card in the card viewer, and in the draw reveal once the flip has finished (#228). Since issue #230 the rank medal and the accolades are no longer in the card viewer: the player name carries the hint "Stats and accolades" and opens the player popup, which shows them.
- **Draw counter** — shows the user's current token balance (e.g. "3 Kana Tokens remaining"), next to the buttons. It is the panel's only balance indicator.
- **Promo code** — under a **Promo code** caption, a text field and Redeem button (`#redeemBtn`) to enter a promo code and receive additional tokens.
- **In-flight lock** (#185) — Draw a card, Draw 1 card from this team, the reroll Confirm and Redeem are disabled from the click until the answer is handled (for a draw, until the reveal shows), so a double click sends one request; a failed request re-enables the button and shows the error. A drawn card joins the roster only when there is room and no roster card has the same player; otherwise the reveal says it went to the bench.
- **How scoring works →** — a link that switches to the How to Play tab.
- **Status line** (`#deckStatus`) — empty unless a draw fails; then it shows the error.
- **Landed notice** (`#drawLandedNotice`, phone only, below 768 px) — the roster sits above the Draw panel, so on Continue the card flies up off the top edge and a notice at the top of the screen says "Added to active roster" or "Added to bench" with **See roster ↑** for 5 seconds. See roster scrolls up to the roster, where the new card glows once.

## My Roster panel

Displays the user's current active cards (up to 5) and bench cards for a selected week.

### Week selector

A dropdown listing all season weeks. Locked past weeks are labelled with a checkmark (✓). The current active week is labelled "(upcoming)" when it hasn't started yet. Selecting a past week shows the immutable snapshot from that week. The chosen week stays selected when the tab refreshes; with no choice made, the upcoming week (the first week that has not started) is selected.

### Roster locked banner

Shown for locked weeks only: "Roster locked — {week label} snapshot". The first time a locked week is opened it stamps in with a lock icon (see Motion).

### Active roster grid

Five fixed card positions (`#rosterActiveGrid`), each showing the card image with its weekly points ("{pts} pts") underneath. The card image is the original illustrated art (layout A was rolled back by #228), and the card face carries no accolade or tag symbols, on the bench as well: open the card to see the player's tags in the card viewer (#228), and the player's name to see the rank and the accolades in the player popup (#230). Cards sit in their `slot_index` position, so gaps are kept; an empty position shows an "empty slot" placeholder. Clicking a card image opens the card view.

- For the editable week: drag a card to rearrange or move it, with a mouse, a pen or a finger (on touch, hold the card for a quarter of a second to pick it up; a quicker swipe scrolls the page). The card lifts and follows the pointer, both zones light up, and the roster makes room live: in a zone the other cards slide aside, and a bench card over a roster card dims that card with an arrow to the bench (a swap). Near the top or bottom of the screen the page scrolls. Dropping a roster card on another roster card moves it to that position; on an empty slot, it moves there; on the bench, it goes before the bench card under it (or last). Dropping a bench card on a roster card swaps the two; on an empty slot (or the roster area), it joins the roster there. Dropping a bench card on the bench reorders it. The move shows at once and the cards glide into place. A move that breaks a rule (full roster, a second card of the same player, a removed player) glides back and the status line names the rule. Releasing outside both zones, Escape or a cancelled touch puts the card back. A focused card image toggles between roster (first free slot) and bench (front) with Enter or Space. Changes save automatically; nothing blocks the next move while a save runs.
- For locked weeks: read-only; cards can't be picked up and Enter or Space does nothing. Clicking a card still opens it.
- After bench substitution has run for a locked week, a bench card that was swapped in sits in the slot of the card it replaced, with a **"Subbed in for {player}"** label under its points.

### Roster totals

A line under the grid (`#rosterTotals`):

- **This week** — sum of fantasy points earned by the roster cards during the selected week's matches.
- **Season** — cumulative fantasy points earned across all locked weeks (only counting cards that were in the active roster snapshot for each week, after any bench substitution).
- **Status** (`#rosterStatus`) — "{n}/5 active" for the editable week; empty for locked weeks. Autosave (600 ms after the last move, at once when the page is hidden, the tab or week changes, or the week locks within 2 minutes): "Saving…" while a save runs, then "Saved" for 2 seconds. On a network error: "Couldn't save." with a **Retry** button (`#rosterRetryBtn`), and the layout stays as arranged. When the roster changed elsewhere (another tab, the Twitch panel): the cards glide to the latest layout and it says "Your roster changed elsewhere. Showing the latest." A refused move or save names the rule. When the shown week locked before the save: "Week N locked; this change counts from Week N+1". Leaving the tab never prompts.
- **Substitution note** (`#rosterSubsNote`) — for a locked week whose substitutions haven't run yet: "Substitutions are made {N} hours after the week ends" (N from `substitution_delay_hours`). Hidden otherwise.

### Bench section

A card grid (`#benchGrid`) under a **Bench** heading, in the same card style as the roster. For the editable (upcoming) week: the user's bench, ordered left to right; bench order decides which card comes in first in a bench substitution. For a locked week: the bench saved at lock, read-only, with any subbed-out card first, labelled **"Did not play"**. Hidden for a locked week with no saved bench (weeks locked before bench snapshots existed).

- If the user has no cards on the bench for the editable week, shows "No cards on bench — draw some!".

### Week status label

Shown next to the week selector. For the editable week: "Locks [weekday, date]" in amber. For locked weeks: "In progress" or "Locked" in grey.

## Guided tour

A spotlight tour of this tab (`frontend/app-tour.js`). It starts from **Show the tour** on How to Play → Users; with `GUIDED_TOUR_AUTOSTART=true` it also starts once, automatically, the first time a logged-in player opens My Team in a browser, after any open popup closes.

- A dark overlay covers the page except a cut-out with an orange outline around one element. A text box below it (or above it when there is no room) shows a title, one or two sentences, a counter ("2 / 7"), **Skip** and **Next** (**Done** on the last step).
- Steps, in order: **Draw a card** (`#drawBtn`, with the configured token name and the live team draw cost), **Chances** (`.rarity-grid`), **Your roster** (`#rosterActiveGrid`, with the number of roster slots rendered, `ROSTER_SLOTS` in `app-roster.js`; "up to the roster limit" if the grid is empty), **Weekly lock** (`#rosterWeekSelect`), **Points** (`#rosterTotals`), **Weekly Report** (`#weeklyReportBtn`, the header button; highlighted, not opened), **Leaderboards** (`#tab-btn-leaderboard`). A step whose element is missing or hidden is skipped and the counter adjusts.
- Esc or a click on the dark area skips; Enter or → goes to the next step; ← goes back. Focus moves into the box and returns to the page on close.
- Skip, Done, Esc and a backdrop click all save `fantasy.tourSeen.v1` in `localStorage`, so the automatic start doesn't repeat. The automatic start gives up for that visit if a popup stays open for 10 seconds. The How to Play button always starts it.
- When the tour closes, a waiting "recap is ready" popup (see `weekly-report.md`) appears right away.

## Motion

- **Drawn card lands (#205):** after a draw's Continue, the card flies from the reveal to its roster slot or the bench front and glows once in its rarity colour (see Draw panel).
- **Roster moves (#186):** every move (drag, Enter or Space, a conflict reload) glides the cards that change place from their old position to the new one (about 220 ms); a dropped card glides from where it was released. The picked-up card lifts (slightly larger, with a shadow). Details: `markdown/features/reference/my-team-save-roster.md`.
- **New points (#155):** a roster card whose weekly points rose since this browser last showed the week counts up from the old value (600–2000 ms, longer for bigger gains), with a floating orange "+points" and a short glow on the card. "This week" counts up by the same new points. Nothing plays on the first visit to a week or when points went down.
- **Week locks (#155):** the first time a locked week is opened, the "Roster locked" banner stamps in (300 ms) with a lock icon that closes, and the cards dim to their locked style (slightly desaturated, 400 ms). Locked weeks always show the cards in that dimmed style.
- **Substitutions (#155):** the first time a week's substitution result is shown, each substitution plays in roster order: the subbed-out card slides down to the bench, the substitute rises into its slot and its "Subbed in for {player}" label fades in (700 ms each, 300 ms apart). A changed result (substitutions re-run after an admin week change) plays once more.
- **Tokens (#155):** when the header balance rises (MVP drop, weekly token, promo code, starter grant), the number counts up over 600 ms and the chip pulses once with a floating "+N". Spending updates at once.
- A click anywhere on My Team finishes the running animation at once (a click on a card then only finishes it; the next click opens the card). What was shown is remembered per browser in `localStorage`; with storage blocked nothing breaks, the animations just don't play again reliably. Details: `markdown/features/reference/weekly-recap-animations.md#my-team-motion-issue-155`.
- With `prefers-reduced-motion`, nothing glides, lifts, counts or pulses: the final state shows at once.
