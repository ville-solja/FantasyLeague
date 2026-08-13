# Players tab

Visible to everyone. Two-column layout: the main Players panel on the left, a stack of three
smaller ranking panels on the right.

## Players panel (left)

Table of all players who have participated in any ingested league. Sortable columns: Player
(avatar + name, clickable → Player detail modal), Team, Matches, Avg pts, Total pts, MVPs.

- **Filter** — text field filters rows in real time by player name or team name.

## Right-hand panels

- **Player average performance** — top 10 by average fantasy points, with a "Show all" toggle.
- **Single match performance** — top 10 single-match fantasy point scores.
- **MVP leaderboard** — players ranked by `mvp_count` (highest first), players with zero MVPs
  omitted. Derived client-side from the same data already fetched for the main Players panel
  (no separate endpoint or Refresh button — refreshing the Players panel refreshes this too).

## Player detail modal

Opened by clicking any player name (in this tab or elsewhere). Shows:

- Player avatar, name, and current team.
- Summary stats (total matches, average points, total points).
- **Match history table** — one row per match, columns (in order): MVP star (first column,
  populated only when `is_mvp` is true), Date, Fantasy pts, K/A/D, GPM, Wards, Tower dmg,
  Opponent (linked to the opposing team's detail modal), and a trailing link to the match on
  OpenDota.
