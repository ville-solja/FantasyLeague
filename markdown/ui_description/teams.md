# Teams tab

Visible to everyone.

## Teams panel

Table of every ingested team (issue 211). Above it, the filter chips **All**, **Div 1** and **Div 2** (selected chip uses the shared selected state).

Columns, every one sortable (click a header; again to flip):

- **Team:** logo (or a two-letter monogram), name (opens the team popup).
- **Division:** Div 1 or Div 2, from the league of the team's matches; "—" when unknown.
- **Series W–L:** from the schedule feed (a third number appears when a series was drawn).
- **Games W–L:** from matches.
- **Fantasy pts per game:** the team's players' combined points per game.
- **Players:** players who played for the team this season.
- **Titles:** champion title chips from all seasons; pips at phone width.

Default order: Div 1 before Div 2, then series wins. The chosen filter and sort stay across data refreshes, not across a page reload. Matches excluded from scoring count in no figure.

At phone width each team becomes a stacked block (labels before values); nothing scrolls sideways.

## Team popup

Opened by clicking any team name (`openTeamModal`, in `frontend/app-team-popup.js`). Data comes from `GET /teams/{id}`. Top to bottom:

1. **Header:** logo or monogram, name, "Div 1 · Season 17", and champion title chips ("S16 Div 1 Champion").
2. **Summary tiles:** Series W–L, Games W–L, Pts per game (five players combined), Avg game (mm:ss), MVPs.
3. **Season results:** a form strip of result chips, then one row per series: week, opponent (logo, link to its popup), score and a W/L chip. Chips carry the letter as text and a shape (filled W, hollow L, dashed D), with the full result as their label. **Upcoming** lists the next series with date and time and a stream link when the feed has one.
4. **Roster:** sortable table (Player, Role, Games, Avg pts, Total pts, Share, Owned; default total points, descending). Each row: avatar, name (opens the player popup), tag and accolade pips, Core or Support chip, games as "12 / 13", average and total points, a share-of-team-points bar with its percentage, and "Owned by N %". Ownership shows once at least 10 managers have cards; until then the column shows "—". Players with under 30 % of the team's games are grouped under **Also played**. Stacked rows at phone width.
5. **Where the points come from:** the stacked bar by source per team game, a row per source with a tick for the average team, and "A +10 % modifier pays most on this team's players: …".
6. **Heroes:** the six most picked heroes with games, W–L and the players who played them.

**Empty state:** with no games this season the popup shows "No matches yet this season."; the header, titles and any upcoming series still show. With the schedule feed down the results list is empty and everything else still shows.
