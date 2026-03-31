# My Team tab

Visible only to logged-in users.

## Deck panel

Shows the current pool of unowned cards available to draw, broken down by rarity (Common, Rare, Epic, Legendary) with a count for each. Below the rarity grid:

- **Draw a card** button — spends 1 token and draws a random card from the shared deck. On success a reveal modal pops up showing the card rarity, player name, team, and player avatar.
- **Draw counter** — shows the user's current token balance (e.g. "3 Kana Tokens remaining").
- **Promo code** — a text field and Redeem button to enter a promo code and receive additional tokens.
- **Scoring info toggle** — a collapsible explanation of how fantasy points are calculated from match stats.

## My Roster panel

Displays the user's current active cards (up to 5) and bench cards for a selected week.

### Week selector

A dropdown listing all season weeks. Locked past weeks are labelled with a checkmark (✓). The current active week is labelled "(upcoming)" when it hasn't started yet. Selecting a past week shows the immutable snapshot from that week.

### Roster locked banner

Shown for locked past weeks only. Displays the week label and a message confirming the roster is a read-only snapshot.

### Active table

Columns: Player (avatar + name), Rarity badge, Weekly pts, Action.

- For the editable week: each row has a **Bench** button to move the card off the active roster.
- For locked weeks: the Action column is empty (read-only).
- Empty slots (fewer than 5 active cards) are shown as greyed-out "— empty slot —" rows.

### Roster totals (table footer)

- **This week** — sum of fantasy points earned by active cards during the current week's matches.
- **Season total** — cumulative fantasy points earned across all locked weeks (only counting cards that were in the active roster snapshot for each week).

### Bench section

Shown only for the editable (upcoming) week. Hidden for locked past weeks.

Columns: Player, Rarity, Weekly pts, Action.

- Each bench card has an **Activate** button (or a "Roster full" label if 5 cards are already active).
- If the user owns cards but none are on the bench, shows "No cards on bench".

### Week status label

Shown next to the week selector. For the editable week: "Locks [weekday, date]" in amber. For locked weeks: "In progress" or "Locked" in grey.
