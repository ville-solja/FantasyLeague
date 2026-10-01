# My Team tab

Visible only to logged-in users.

## Layout

On desktop (≥ 768 px) the tab uses a two-column grid: **My Roster** occupies the main column (`1fr`) on the left and **Draw** occupies a fixed 300 px sidebar on the right. On narrow viewports (< 768 px) the columns collapse to a single stack — Roster first, Draw sidebar below.

## Draw panel

Under a **Chance per draw** caption, shows the rarity drop percentages for the current draw pool, broken down by rarity (Common, Rare, Epic, Legendary) with a normalised percentage for each (e.g. 60%, 25%, 10%, 5%). Percentages come from the live `draw_rate_*` scoring weights and always sum to 100%. Below the rarity grid:

- **Draw a card** button — spends 1 token and draws a random card from the shared deck. On success the client **prefetches** the card PNG while opening the modal. Reveal: a **full-viewport light burst + sparkles** (~2.1–2.35s, rarity-colored) and a **slower slot entrance** (~1.45s) with matching rim glow. The card-back stays up until **`img.decode()`** and a **short minimum (~850ms)** from open (whichever is later); the burst layer is cleared **after** the art is visible (~320ms later). Slow PNGs still wait on the network; fast ones are not held for the full burst duration. Server PNG encoding favors **lower latency** over smallest file. **`prefers-reduced-motion`**: no burst/sparkles, static card-back, soft slot fade, ~320ms floor. **Rolled stat modifiers** are painted on the card image (lower band). Reroll: decode handoff + brief brightness flash on the image only.
- **Draw from a team (N Tokens)** button (`#boosterBtn`) — next to the standard draw. N is the live `team_booster_cost` from `GET /config` (fallback 3) and the token name comes from config. Disabled with a tooltip when logged out or when the balance is below N. Opens the team picker.
- **Draw hint** (`#boosterHint`) — a muted line under the buttons: "1 token for a random player, or N for a player from a team you pick. You get players you don't own yet first." N (`#boosterHintCost`) is filled from `team_booster_cost` in `GET /config`.
- **Team picker** (`#boosterModal`, titled "Choose a team") — a cost line "Costs N Tokens for 1 card", a grid of team tiles showing how many unowned players are left (fully collected teams are greyed out and read "Complete"), and Cancel / **Draw 1 card from this team** buttons. The confirm button is enabled once a team is selected. After a team draw, the reveal modal's "Draw another card" repeats a team draw from the same team.
- **Draw reveal copy** — player and team names are **only on the card PNG** (not duplicated under the image), so layout tweaks in the generator (`_PLAYER_NAME_Y`, `_TEAM_NAME_Y`) match what you see. Opening a card from the roster without draw animation still shows name and team under the art.
- **Draw counter** — shows the user's current token balance (e.g. "3 Kana Tokens remaining"), next to the buttons. It is the panel's only balance indicator.
- **Promo code** — under a **Promo code** caption, a text field and Redeem button to enter a promo code and receive additional tokens.
- **How scoring works →** — a link that switches to the How to Play tab.
- **Status line** (`#deckStatus`) — empty unless a draw fails; then it shows the error.

## My Roster panel

Displays the user's current active cards (up to 5) and bench cards for a selected week.

### Week selector

A dropdown listing all season weeks. Locked past weeks are labelled with a checkmark (✓). The current active week is labelled "(upcoming)" when it hasn't started yet. Selecting a past week shows the immutable snapshot from that week.

### Roster locked banner

Shown for locked weeks only: "Roster locked — {week label} snapshot".

### Active roster grid

Five fixed card positions (`#rosterActiveGrid`), each showing the card image with its weekly points ("{pts} pts") underneath. Cards sit in their `slot_index` position, so gaps are kept; an empty position shows an "empty slot" placeholder. Clicking a card image opens the card view.

- For the editable week: drag a card to rearrange or move it. Dropping a roster card on another roster card moves it to that position; on an empty slot, it moves there. Dropping a roster card on the bench benches it (placed at the front of the bench). Dropping a bench card on a roster card swaps the two; on an empty slot, it activates the card in that slot. Dropping a bench card on another bench card reorders the bench. A focused card image toggles between roster and bench with Enter or Space. Errors (for example a full roster or a duplicate player) appear in the status line.
- For locked weeks: read-only; no dragging or keyboard toggling.
- After bench substitution has run for a locked week, a bench card that was swapped in sits in the slot of the card it replaced, with a **"Subbed in for {player}"** label under its points.

### Roster totals

A line under the grid:

- **This week** — sum of fantasy points earned by the roster cards during the selected week's matches.
- **Season** — cumulative fantasy points earned across all locked weeks (only counting cards that were in the active roster snapshot for each week, after any bench substitution).
- **Status** (`#rosterStatus`) — "{n}/5 active" for the editable week; empty for locked weeks; shows the error when a roster change fails.
- **Substitution note** (`#rosterSubsNote`) — for a locked week whose substitutions haven't run yet: "Substitutions are made {N} hours after the week ends" (N from `substitution_delay_hours`). Hidden otherwise.

### Bench section

A card grid (`#benchGrid`) under a **Bench** heading, in the same card style as the roster. For the editable (upcoming) week: the user's bench, ordered left to right; bench order decides which card comes in first in a bench substitution. For a locked week: the bench saved at lock, read-only, with any subbed-out card first, labelled **"Did not play"**. Hidden for a locked week with no saved bench (weeks locked before bench snapshots existed).

- If the user has no cards on the bench for the editable week, shows "No cards on bench — draw some!".

### Week status label

Shown next to the week selector. For the editable week: "Locks [weekday, date]" in amber. For locked weeks: "In progress" or "Locked" in grey.
