# Leaderboards tab

Visible to everyone (no login required). Default tab on page load.

## Standings panel

Fantasy user standings with two modes toggled by buttons:

- **Season** (default) — ranks all users by cumulative fantasy points earned across all locked weeks. Points are only counted for cards that were in the user's active roster snapshot for each week, after bench substitution (subbed-in bench cards count, subbed-out cards don't). Shows columns: Rank, User, Season pts.
- **Weekly** — ranks users by points earned in a single week. A week dropdown appears to select which past locked week to view; the chosen week stays selected when the tab refreshes. Shows columns: Rank, User, Week pts.

A real admin's name carries an **ADMIN** badge (issue #169) in the Season and Weekly views and in Past Seasons. It comes only from the account's admin flag. User tags follow the name in the Season and Weekly views. Both are role badges (`adminBadgeHtml`, `tagBadgeHtml`): ADMIN in the admin colour, Caster and Season Winner in their own colours, other tags neutral; no tag can take the admin colour, and each badge's hover text gives its reason. Usernames and tag labels are HTML-escaped. Badge shapes and colours follow the design system's "States and emphasis" rules (`.claude/skills/README.md`).

**Your row:** when logged in, your row in the Season, Weekly and Past Seasons views is marked as yours (`.row-self`): the whole row is tinted, its text is bold and a "(You)" status badge follows your name; in the Weekly view the expanded card chips row gets the same tint. Logged out, no row is marked. See "Self" in the design system's "States and emphasis" rules (`.claude/skills/README.md`).

Tester accounts and Twitch viewer soft accounts (players who joined in the Twitch panel, issue #157) never appear in either view or in Past Seasons.

Card rarity modifiers are applied to points in both views (e.g. a Legendary card gets +3% on top of raw stats).

In the Weekly view, clicking a row expands that user's card chips: rarity, player name, the card's points for that week (the same stored week value My Team shows) and the number of games behind them, e.g. `86.3 · 4 games` or `21.1 · 1 game` (issue #250). The chip's tooltip reads "Glete (common): 86.3 points from 4 games this week". The Season view shows totals only and does not expand into chips. The API rounds each card value and each user total once, to 1 decimal, each from its own exact sum (see `markdown/features/reference/points-rounding.md`), and the page shows that value as is. A one-line note under the chips says "Card points are the week's total over every game the player played, rounded from exact points."

## Past seasons panel

Panel `#pastSeasonsPanel` with the heading "Past Seasons" and a season dropdown (`#pastSeasonSelect`) listing archived seasons. Shows the selected season's final standings. Columns: Rank, User, Points. Hidden when there are no archived seasons or when loading the list fails. The selected season stays selected when the tab refreshes. A failed standings load shows the error in `#pastSeasonStatus`.

The Player average performance and Best single games panels are on the Players tab; see `players.md`.
