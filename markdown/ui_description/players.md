# Players tab

Visible to everyone. Two-column layout: the main Players panel on the left, a stack of three
smaller ranking panels on the right.

## Players panel (left)

Table of all players who have participated in any ingested league. Sortable columns: Player
(avatar + name, clickable → Player detail modal), Team, Seasons, Titles, Matches, Avg pts, Total pts, MVPs.

- **Filter** — text field filters rows in real time by player name or team name.
- **Filter chips** (issue #50) — All, Champions (a champion title in any season) and New this season
  (one season played, the current one). Selected chips follow "States and emphasis" in the design system.
- **Seasons** — the seasons-played count in tabular numbers (recorded seasons plus the current one when
  the player has a scored match), then one bar per season for the last six known seasons: grey played,
  amber a champion season, empty not played. Hovering or focusing the count lists the seasons.
- **Titles** — the player's accolade pips (champion and award titles; Played is the Seasons column).
  Each pip shows its name and seasons on hover, focus or tap. Sorting by Titles counts them.
  There is no Veteran status. See `features/reference/season-winners-and-holo-cards.md`.

## Right-hand panels

- **Player average performance** — top 10 by average fantasy points, with a "Show all" toggle. The toggle state and the main table's sort column stay when the tab refreshes.
- **Single match performance** — top 10 single-match fantasy point scores.
- **MVP leaderboard** — players ranked by `mvp_count` (highest first), players with zero MVPs
  omitted. Derived client-side from the same data already fetched for the main Players panel
  (no separate endpoint or Refresh button — refreshing the Players panel refreshes this too).

## Player detail modal

Opened by clicking any player name (in this tab or elsewhere). Shows:

- Player avatar, name, and current team, with the accolade pips under the name (issue #50).
- Summary stats (total matches, average points, total points).
- **Accolades** section (only when the player has any): a "Holo unlocked" banner for a past
  champion, counts (champion titles, season awards, seasons played) and a timeline by season,
  newest first, each season with its chips ("S16 Div 1 Champion"; the current season's
  "S16 Played · 7 matches").
- **Match history table** — one row per match, columns (in order): MVP star (first column,
  populated only when `is_mvp` is true), Date, Fantasy pts, K/A/D, GPM, Wards, Tower dmg,
  Opponent (linked to the opposing team's detail modal), and a trailing link to the match on
  OpenDota. The Fantasy pts cell carries a "Partial stats" badge for a match whose replay is
  unparsed or unparseable. Its tooltip says wards, stuns, teamfight, runes and camps count as 0.
  A match an admin excluded from scoring shows a dash and a "Not scored" badge instead, and is
  left out of the summary's average, total and best-match points.
