# Leaderboards tab

Visible to everyone (no login required). Default tab on page load.

## Standings panel

Fantasy user standings with two modes toggled by buttons:

- **Season** (default) — ranks all users by cumulative fantasy points earned across all locked weeks. Points are only counted for cards that were in the user's active roster snapshot for each week, after bench substitution (subbed-in bench cards count, subbed-out cards don't). Shows columns: Rank, User, Season pts.
- **Weekly** — ranks users by points earned in a single week. A week dropdown appears to select which past locked week to view; the chosen week stays selected when the tab refreshes. Shows columns: Rank, User, Week pts.

A real admin's name carries an **ADMIN** badge (issue #169) in the Season and Weekly views and in Past Seasons: an outlined chip in the accent colour, display type, uppercase, 2px radius, 11px. It comes only from the account's admin flag and looks different from the filled flame tag chips, which no admin can name `admin`. Usernames and tag labels are HTML-escaped.

Tester accounts and Twitch viewer soft accounts (players who joined in the Twitch panel, issue #157) never appear in either view or in Past Seasons.

Card rarity modifiers are applied to points in both views (e.g. a Legendary card gets +3% on top of raw stats).

In the Weekly view, clicking a row expands that user's card chips: rarity, player name and the card's points for that week, the same stored week value My Team shows. The Season view shows totals only and does not expand into chips. The API rounds each card value and each user total once, to 1 decimal, each from its own exact sum (see `markdown/features/reference/points-rounding.md`), and the page shows that value as is. So the chips can add up to a slightly different number than the total (typically 0.1); a one-line note under the chips says "Totals are rounded from exact points, so card values may differ by 0.1 in sum."

## Past seasons panel

Panel `#pastSeasonsPanel` with the heading "Past Seasons" and a season dropdown (`#pastSeasonSelect`) listing archived seasons. Shows the selected season's final standings. Columns: Rank, User, Points. Hidden when there are no archived seasons or when loading the list fails. The selected season stays selected when the tab refreshes. A failed standings load shows the error in `#pastSeasonStatus`.

The Player average performance and Single match performance panels are on the Players tab; see `players.md`.
