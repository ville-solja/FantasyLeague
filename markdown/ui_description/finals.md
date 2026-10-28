# Finals tab (#237)

Tab button between Schedule and How to Play, hidden until `GET /config` reports `finals_available` (every Div 1 team has played a group series, or the bracket is set) and hidden again once the season is archived. Opening the tab loads `GET /finals`; **Refresh** reloads it.

**Style:** the Kana Cards design system only (`colors_and_type.css` tokens, "States and emphasis" in `.claude/skills/README.md`), never the fixtures site's look. Dark, like the app. Match cards are `.panel` surfaces; team names and labels use Big Shoulders caps; teams show their logo or the two-letter monogram (as on the Teams tab); a picked team uses the shared selected state (accent border and tint, inverted on hover or focus); a winner is a bold `.mark-winner` name under an amber "Winner" label; "Live" is the shared `.live-tag`.

- **Heading:** "Div 1 Finals" with **Refresh**.
- **Header line** by state: "N/28 group series played" (projected), "Seeding waits for a tiebreak decision", "Predictions close when the first semi-final game starts" (open), "Predictions are paused", "Predictions closed" (locked) or "The finals are decided".
- **Match tree:** semi-final 1 and semi-final 2 in the left column, the grand final on the right, joined by connector lines (an inline SVG in `--border`). At 720 px and below the tree is one column (semi-final 1, semi-final 2, grand final), the connectors are hidden, and nothing scrolls sideways.
- **Match card:** the series label, **Live** while one of its games is in the live list, and the series score once games are in. Then two team rows: logo and name; before the bracket is set, a "?" chip, the slot ("1st place") and "now <team>" in muted text, or "tie: <team>, <team>" for a shared rank. The grand final shows "Winner of semi-final 1" and "Winner of semi-final 2" until the semis are decided.
- **Predictions:**
  - **Open, logged in:** the semi team rows are pick buttons (`aria-pressed`, at least 44 px tall). The grand final offers only the user's two semi picks ("Pick both semi-final winners first" until then); changing a semi pick clears a final pick that is no longer one of them. Each card shows "Your pick: <team>". **Save predictions** sends all three; a missing pick shows "Pick a winner for both semi-finals and the grand final" in the status line. A refused save shows the server's reason; a `409` reloads the tab.
  - **Open, logged out:** the tree with **Log in to predict** (opens the login dialog).
  - **Locked:** read-only rows with each team's share of picks in %, "N predictions" under each card, and "Your pick: <team>".
  - **Decided:** the winner line on each decided card, own picks marked **Correct** or **Wrong** next to "Your pick", and below the tree "You got N of 3" (when the user predicted) and "M users got all three".
- Team names are always escaped; no other user's individual picks are ever shown.

Admin side: Admin › Settings › Season › **Season Finals** (see `admin.md`). Details: `markdown/features/core/finals-predictions.md`.
