# Leaderboards tab

Visible to everyone (no login required). Default tab on page load.

## Standings panel

Fantasy user standings with two modes toggled by buttons:

- **Season** (default) — ranks all users by cumulative fantasy points earned across all locked weeks. Points are only counted for cards that were in the user's active roster snapshot for each week, after bench substitution (subbed-in bench cards count, subbed-out cards don't). Shows columns: Rank, User, Season pts.
- **Weekly** — ranks users by points earned in a single week. A week dropdown appears to select which past locked week to view. Shows columns: Rank, User, Week pts.

Card rarity modifiers are applied to points in both views (e.g. a Legendary card gets +3% on top of raw stats).

In the Weekly view, clicking a row expands that user's card chips: rarity, player name and the card's points for that week, the same stored week value My Team shows. The Season view shows totals only and does not expand into chips. The API rounds each card value and each user total once, to 1 decimal, each from its own exact sum (see `markdown/features/reference/points-rounding.md`), and the page shows that value as is. So the chips can add up to a slightly different number than the total (typically 0.1); a one-line note under the chips says "Totals are rounded from exact points, so card values may differ by 0.1 in sum."

## Player average performance panel

Ranks all players in the league by average fantasy points per match. Columns: Rank, Player (clickable → Player detail modal), Matches, Avg pts.

## Single match performance leaderboard panel

Ranks individual player-match results by fantasy points earned in a single game. Shows the top performances across the entire season. Columns: Rank, Player (clickable → Player detail modal), Fantasy pts.
