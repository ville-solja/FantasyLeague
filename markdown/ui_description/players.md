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

Opened by clicking any player name or card (in this tab or elsewhere); the code is in
`frontend/app-player-popup.js`. Sections, top to bottom (issue 208):

- **Header** — avatar, name and current team; the accolade pips (issue 50); seasons played and a
  Core or Support chip (Support when this season's average wards are 3 or more and GPM is under 450;
  no chip without a scored match).
- **Summary tiles** — Matches with W–L, Avg pts with the league rank ("#7 of 84", only with 3+
  scored matches), Total pts, Best match with its opponent, MVPs.
- **Form chart** — one bar per match, oldest left, grouped under scoring-week labels ("W3"). Bar
  height is fantasy points. A star marks the MVP, a filled square a win and a hollow square a loss;
  an excluded match is a dashed ghost bar ("Not scored"), a partial-stats match is hatched. A solid
  line marks the player's average and a dashed line the league average per match, each labelled.
  Bars are buttons: hover, focus or tap shows a tooltip (date, opponent, hero, result, points,
  K/D/A) and activating one scrolls to and highlights its history row. The chart's `aria-label`
  summarises it. Bars grow once on open; nothing moves under reduced motion.
- **Points by source** — a 100 % stacked bar (top five sources in the chart series colours, the rest
  as Other) and a row per source with average points per match, share and a tick for the league
  average. Below it: "A +10 % modifier is worth most on: …" with the top three stats, and every
  stat's modifier value; when the signed-in viewer owns a card of this player (from the loaded My
  Team data), that card's modifiers are marked with their value per match.
- **Compared with the league** — percentile strips for Kills, Deaths, Assists, GPM, Last hits,
  Wards, Stuns and Teamfight %: the average, a track with the median tick and the player's dot, and
  "Top 15 %" / "Bottom 30 %" (Deaths: "Fewer deaths than 80 % of players"), against players with 3+
  scored matches ("vs 84 players"). Below 3 matches: "Not enough matches to compare yet".
- **Heroes** — this season's heroes with games, W–L and average points, six then "Show all". When
  profile facts exist, a "Career (OpenDota, updated <date>)" list with games and win rate.
- **Accolades** section (only when the player has any): a "Holo unlocked" banner for a past
  champion, counts (champion titles, season awards, seasons played) and a timeline by season,
  newest first, each season with its chips ("S16 Div 1 Champion"; the current season's
  "S16 Played · 7 matches").
- **Match history table** — one row per match, columns (in order): MVP star, Date, Hero (icon),
  Result (W or L as text, blank when unknown), Fantasy pts, K/A/D, GPM, Wards, Tower dmg, Opponent
  (linked to the opposing team's detail modal), a link to the match on OpenDota, and a **Details**
  toggle (`aria-expanded`) that opens every stat of the match (including last hits, denies,
  towers, Roshan, teamfight, camps, runes, first blood, stuns, sentry wards and duration) and its
  points breakdown by source with the MVP bonus. The Fantasy pts cell carries a "Partial stats"
  badge for a match whose replay is unparsed or unparseable. Its tooltip says wards, stuns,
  teamfight, runes and camps count as 0. A match an admin excluded from scoring shows a dash and a
  "Not scored" badge instead, and counts in no tile, average, breakdown, comparison or hero figure.
  Below 640 px each match is one stacked row (date, hero, opponent, result, points) with the same
  Details toggle; nothing scrolls sideways.
- **Profile facts and bio** — last, unchanged (the admin-run profile enrichment).

With no matches this season, the tiles, chart and the sections below are replaced by "No matches
yet this season." (the accolades and bio still show).
