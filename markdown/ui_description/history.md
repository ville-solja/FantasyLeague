# History tab

Visible to everyone, after Leaderboards in the tab bar (issue #50). Served by `GET /history/seasons` (public, no user ids).

## Season panels

One panel per season, newest first:

- **Champions** — two blocks, Div 1 and Div 2, each headed by its chip ("S16 Div 1 Champion"), then the team name and its players, each with a **Holo** status badge (past champions' Legendaries can be drawn as Holo). Champions of the current season show **Holo from next season** instead: they become Holo-eligible once the season has ended. A division without a record reads "No champion recorded". Under it, the division's **Runner-up** and **Third place** teams (issue 233), each as its chip ("S15 Div 1 Runner-up") and the team name, when recorded.
- **Awards** — Most Points, Best Average, Best Single Match and Fantasy Winner as data rows: the chip, the winners' names (all tied winners) and the value in tabular numbers.
- **Played** — "N players played" when the season has played records.

## Hall of fame (sidebar)

Players ranked by titles (champion, runner-up, third place and awards; seasons played don't count), each with their accolade pips and title count. Below 760 px the sidebar moves under the season panels.

## Empty state

"No season history yet." in place of the panels.

Symbols follow the design system's "Accolade symbols" (pips for a glance, chips where the names fit). See `markdown/features/reference/season-winners-and-holo-cards.md`.
